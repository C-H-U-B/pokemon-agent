"""OpenClaw (sans guard) contre l'agent ADK (avec guard) sur des cas à contraintes de la campagne structurée.

Même modèle des deux côtés (Qwen dans LM Studio). Côté OpenClaw, chaque question part par `openclaw agent`
dans une session neuve ; le relais (`scripts/openclaw_relay.py`), lancé ici sur le port 1235, enregistre ce
que reçoit et renvoie le modèle, d'où l'on tire les appels d'outils et la réponse. Côté ADK, les mêmes cas
sont relus dans le dernier run de `test_results/adk_structured_database_e2e.jsonl` qui les contient tous.
Un seul correcteur pour les deux : outil attendu appelé, arguments attendus (ceux exécutés ; pour ADK, aussi
ceux proposés par Qwen avant le guard), termes attendus présents et termes interdits absents de la réponse.

Appelle un LLM : à lancer par l'utilisateur. Prérequis : LM Studio servi sur 1234 avec le modèle chargé,
gateway OpenClaw démarré, `models.providers.lmstudio.baseUrl` d'OpenClaw = http://localhost:1235/v1.

    python benchmarks/benchmark_openclaw_vs_adk.py
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test_results"
CASE_IDS = (
    "level-opermine-range", "machine-gouroutan-sun-moon", "search-national-number", "mega-slowest-tie",
    "heaviest-tie", "stats-mega-dardargnan", "moves-combined", "dans-is-not-a-game",
    "top-five-ghost-special-attack", "typo-singular-attack-is-the-statistic",
)
TOOL_PREFIX = "pokemon__"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grade(case, calls: list[dict], answer: str, e2e) -> dict:
    """Mêmes critères pour les deux agents, termes comparés comme dans la campagne ; `calls` = [{"name", "args"}]."""
    call = next((c for c in calls if c["name"] == case.expected_tool), None)
    args = call["args"] if call else {}
    arg_matches = e2e._arg_matches
    missing, forbidden = e2e.answer_term_failures(case, answer)
    wrong_args = {k: args.get(k) for k, v in case.expected_args.items() if not arg_matches(args.get(k), v, k)}
    return {
        "tool_ok": call is not None, "args_ok": call is not None and not wrong_args, "wrong_args": wrong_args,
        "answer_ok": bool(answer.strip()) and not missing and not forbidden,
        "missing_terms": missing, "forbidden_terms": forbidden,
    }


def adk_reference(cases) -> tuple[str, dict]:
    rows = [json.loads(line) for line in (RESULTS / "adk_structured_database_e2e.jsonl").open(encoding="utf-8")
            if line.strip()]
    by_run: dict[str, dict] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], {})[row["case_id"]] = row
    run = max(r for r, found in by_run.items() if all(c.id in found for c in cases))
    return run, by_run[run]


def adk_calls(row: dict) -> tuple[list[dict], list[dict]]:
    """Appels exécutés après le guard (refusés exclus) et propositions de Qwen avant lui, défauts compris."""
    calls = row.get("executed_calls") or []
    executed = [{"name": c["name"], "args": c["effective_args"]} for c in calls if not c.get("blocked")]
    proposed = [{"name": c["name"], "args": c["proposed_effective_args"]} for c in calls]
    return executed, proposed


def _stream_message(raw: str) -> tuple[str, list[dict]]:
    """Texte et appels d'outils d'une réponse SSE de type OpenAI."""
    text, calls = "", {}
    for line in raw.splitlines():
        if not line.startswith("data: {"):
            continue
        for choice in json.loads(line[6:]).get("choices", []):
            delta = choice.get("delta") or {}
            text += delta.get("content") or ""
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
                fn = tc.get("function") or {}
                slot["name"] += fn.get("name") or ""
                slot["arguments"] += fn.get("arguments") or ""
    return text, [{"name": c["name"], "args": json.loads(c["arguments"] or "{}")} for c in calls.values()]


def openclaw_transcript(capture_dir: Path, session_id: str | None = None) -> tuple[list[dict], str]:
    """Appels d'outils (préfixe du serveur retiré) et réponse finale, lus dans les captures du relais.

    Comme dans la campagne ADK, un argument omis vaut son défaut de schéma (lu dans la requête capturée).
    Avec `session_id`, les requêtes d'une autre session (reprise par le gateway au démarrage) sont ignorées.
    """
    calls, answer = [], ""
    for resp in sorted(capture_dir.glob("*.resp.txt")):
        raw_request = resp.with_name(resp.name.replace(".resp.txt", ".json")).read_text(encoding="utf-8")
        request = json.loads(raw_request)
        if not request.get("tools"):  # titre de session, compaction : hors tour d'agent
            continue
        if session_id and f":{session_id}" not in raw_request:
            continue
        defaults = {t["function"]["name"]: {k: p["default"] for k, p in
                                            t["function"].get("parameters", {}).get("properties", {}).items()
                                            if "default" in p}
                    for t in request["tools"]}
        text, made = _stream_message(resp.read_text(encoding="utf-8", errors="replace"))
        calls += [{"name": c["name"].removeprefix(TOOL_PREFIX), "args": {**defaults.get(c["name"], {}), **c["args"]}}
                  for c in made]
        if text.strip() and not made:
            answer = text
    return calls, answer


def session_id(case, run_tag: str) -> str:
    return f"eval-{case.id}-{run_tag}"


def run_openclaw(case, run_tag: str, capture_dir: Path, relay_module, timeout: int) -> float:
    capture_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 1235),
                                 relay_module.make_handler(capture_dir, "http://localhost:1234", False))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    message = capture_dir / "question.txt"
    message.write_text(case.question, encoding="utf-8")
    started = time.monotonic()
    try:
        subprocess.run([shutil.which("openclaw"), "agent", "--session-id", session_id(case, run_tag),
                        "--message-file", str(message), "--timeout", str(timeout)],
                       capture_output=True, timeout=timeout + 60, check=False)
    finally:
        server.shutdown()
        server.server_close()
    return time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=int, default=600, help="délai maximal d'un cas, en secondes")
    args = parser.parse_args()
    if shutil.which("openclaw") is None:
        sys.exit("openclaw introuvable dans le PATH")

    e2e = _load(ROOT / "tests" / "long" / "test_adk_structured_database_e2e.py", "adk_structured_e2e")
    relay = _load(ROOT / "scripts" / "openclaw_relay.py", "openclaw_relay")
    cases = [c for c in e2e.CASES if c.id in CASE_IDS]
    adk_run, adk_rows = adk_reference(cases)
    run_id = datetime.now().astimezone().isoformat(timespec="seconds")
    run_tag = datetime.now().strftime("%Y%m%d%H%M%S")
    capture_root = Path(tempfile.mkdtemp(prefix="openclaw_eval_"))

    records = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.id} : {case.question}", flush=True)
        elapsed = run_openclaw(case, run_tag, capture_root / case.id, relay, args.timeout)
        calls, answer = openclaw_transcript(capture_root / case.id, session_id(case, run_tag))
        adk = adk_rows[case.id]
        adk_executed, adk_proposed = adk_calls(adk)
        record = {
            "run_id": run_id, "case_id": case.id, "question": case.question, "adk_run_id": adk_run,
            "openclaw": {"elapsed_seconds": round(elapsed, 1), "tool_calls": calls, "final_answer": answer,
                         **grade(case, calls, answer, e2e)},
            "adk": {"elapsed_seconds": adk["elapsed_seconds"], "final_answer": adk["final_answer"],
                    "proposed_args_ok": grade(case, adk_proposed, "", e2e)["args_ok"],
                    **grade(case, adk_executed, adk["final_answer"], e2e)},
        }
        records.append(record)
        oc = record["openclaw"]
        print(f"    OpenClaw : réponse {'juste' if oc['answer_ok'] else 'FAUSSE'}, "
              f"arguments {'conformes' if oc['args_ok'] else oc['wrong_args']}, {oc['elapsed_seconds']} s", flush=True)

    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "openclaw_vs_adk.jsonl").open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def total(agent, key):
        return sum(r[agent][key] for r in records)

    lines = [f"# OpenClaw contre ADK — {run_id}", "",
             f"Cas : {len(records)}. ADK relu dans le run {adk_run}. Captures : {capture_root}", "",
             "| Cas | OpenClaw réponse | OpenClaw arguments | ADK réponse | ADK proposition Qwen | OpenClaw s | ADK s |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in records:
        oc, adk = r["openclaw"], r["adk"]
        lines.append(f"| {r['case_id']} | {'ok' if oc['answer_ok'] else 'KO'} | "
                     f"{'ok' if oc['args_ok'] else oc['wrong_args']} | {'ok' if adk['answer_ok'] else 'KO'} | "
                     f"{'ok' if adk['proposed_args_ok'] else 'corrigée'} | {oc['elapsed_seconds']} | {adk['elapsed_seconds']} |")
    lines += ["", f"Réponses justes : OpenClaw {total('openclaw', 'answer_ok')}/{len(records)}, "
                  f"ADK {total('adk', 'answer_ok')}/{len(records)}. Arguments exécutés conformes : OpenClaw "
                  f"{total('openclaw', 'args_ok')}, ADK {total('adk', 'args_ok')} ; proposition Qwen conforme "
                  f"chez ADK : {total('adk', 'proposed_args_ok')}."]
    (RESULTS / "openclaw_vs_adk.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-1:]))
    print(f"Rapport : {RESULTS / 'openclaw_vs_adk.md'}")


if __name__ == "__main__":
    main()
