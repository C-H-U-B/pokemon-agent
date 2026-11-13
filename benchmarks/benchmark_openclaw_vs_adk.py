"""OpenClaw (sans guard) contre l'agent ADK (avec guard) sur des cas à contraintes de la campagne structurée.

Même modèle des deux côtés (Qwen dans LM Studio). Côté OpenClaw, chaque question part par `openclaw agent`
dans une session neuve ; ses appels d'outils et sa réponse sont lus dans la trajectoire que la session laisse
(`openclaw sessions export-trajectory`), quel que soit le `baseUrl` configuré. Côté ADK, les mêmes cas
sont relus dans le dernier run de `test_results/adk_structured_database_e2e.jsonl` qui les contient tous.
Un seul correcteur pour les deux : outil attendu appelé, arguments attendus (ceux exécutés ; pour ADK, aussi
ceux proposés par Qwen avant le guard), termes attendus présents et termes interdits absents de la réponse.

Appelle un LLM : à lancer par l'utilisateur. Prérequis : LM Studio servi avec le modèle chargé, gateway
OpenClaw démarré.

    python benchmarks/benchmark_openclaw_vs_adk.py --repeat 3

Avec `--repeat N`, la i-ème exécution d'OpenClaw est comparée au i-ème des N derniers runs ADK contenant
les dix cas : rejouer d'abord la campagne ADK N fois sur ces cas, le même jour, pour comparer à conditions égales.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
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


def adk_reference(cases, count: int = 1) -> list[tuple[str, dict]]:
    """Les `count` derniers runs de la campagne ADK qui contiennent tous les cas, du plus ancien au plus récent."""
    rows = [json.loads(line) for line in (RESULTS / "adk_structured_database_e2e.jsonl").open(encoding="utf-8")
            if line.strip()]
    by_run: dict[str, dict] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], {})[row["case_id"]] = row
    runs = sorted(r for r, found in by_run.items() if all(c.id in found for c in cases))[-count:]
    if len(runs) < count:
        sys.exit(f"{count} runs ADK demandés, {len(runs)} contiennent les {len(cases)} cas")
    return [(r, by_run[r]) for r in runs]


def adk_calls(row: dict) -> tuple[list[dict], list[dict]]:
    """Appels exécutés après le guard (refusés exclus) et propositions de Qwen avant lui, défauts compris."""
    calls = row.get("executed_calls") or []
    executed = [{"name": c["name"], "args": c["effective_args"]} for c in calls if not c.get("blocked")]
    proposed = [{"name": c["name"], "args": c["proposed_effective_args"]} for c in calls]
    return executed, proposed


def tool_defaults() -> dict[str, dict]:
    """Défauts des arguments, lus dans les schémas du serveur MCP : l'export d'OpenClaw tronque `tools.json`."""
    from pokemon_rag.mcp.server import mcp
    return {t.name: {k: p["default"] for k, p in t.input_schema.get("properties", {}).items() if "default" in p}
            for t in asyncio.run(mcp.list_tools())}


def trajectory_calls(events: list[dict], defaults: dict[str, dict]) -> tuple[list[dict], str]:
    """Appels d'outils (préfixe du serveur retiré) et réponse finale d'une trajectoire OpenClaw exportée.

    Comme dans la campagne ADK, un argument omis vaut son défaut de schéma.
    """
    calls, answer = [], ""
    for e in events:
        if e.get("source") != "transcript":
            continue
        if e["type"] == "tool.call":
            name = e["data"]["name"].removeprefix(TOOL_PREFIX)
            calls.append({"name": name, "args": {**defaults.get(name, {}), **(e["data"].get("arguments") or {})}})
        elif e["type"] == "assistant.message":
            content = e["data"]["message"].get("content") or []
            if not any(c.get("type") == "toolCall" for c in content):
                answer = "".join(c.get("text", "") for c in content if c.get("type") == "text") or answer
    return calls, answer


def openclaw_transcript(session: str, export_root: Path, defaults: dict[str, dict]) -> tuple[list[dict], str]:
    """Trajectoire de la session `session`, exportée par `openclaw sessions export-trajectory` (lecture seule)."""
    folder = export_root / ".openclaw" / "trajectory-exports" / session
    if not folder.exists():  # l'export refuse un dossier existant
        export_root.mkdir(parents=True, exist_ok=True)
        subprocess.run([shutil.which("openclaw"), "sessions", "export-trajectory", "--session-key",
                        f"agent:main:explicit:{session}", "--output", session, "--workspace", str(export_root)],
                       capture_output=True, timeout=120, check=True)
    events = [json.loads(line) for line in (folder / "events.jsonl").open(encoding="utf-8") if line.strip()]
    return trajectory_calls(events, defaults)


def session_id(case, run_tag: str) -> str:
    return f"eval-{case.id}-{run_tag}"


def run_openclaw(case, session: str, work_dir: Path, timeout: int) -> float:
    work_dir.mkdir(parents=True, exist_ok=True)
    message = work_dir / f"{session}.txt"
    message.write_text(case.question, encoding="utf-8")
    started = time.monotonic()
    done = subprocess.run([shutil.which("openclaw"), "agent", "--session-id", session,
                           "--message-file", str(message), "--timeout", str(timeout)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout + 60, check=False)
    if done.returncode:
        print(f"    openclaw agent : code {done.returncode}\n{done.stderr[-800:]}", flush=True)
    return time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=int, default=600, help="délai maximal d'un cas, en secondes")
    parser.add_argument("--repeat", type=int, default=1,
                        help="exécutions d'OpenClaw ; la i-ème est comparée au i-ème des N derniers runs ADK complets")
    args = parser.parse_args()
    if shutil.which("openclaw") is None:
        sys.exit("openclaw introuvable dans le PATH")

    e2e = _load(ROOT / "tests" / "long" / "test_adk_structured_database_e2e.py", "adk_structured_e2e")
    cases = [c for c in e2e.CASES if c.id in CASE_IDS]
    adk_runs = adk_reference(cases, args.repeat)
    defaults = tool_defaults()
    run_id = datetime.now().astimezone().isoformat(timespec="seconds")
    capture_root = Path(tempfile.mkdtemp(prefix="openclaw_eval_"))

    records = []
    for rep, (adk_run, adk_rows) in enumerate(adk_runs, 1):
        run_tag = f"{datetime.now():%Y%m%d%H%M%S}r{rep}"
        for i, case in enumerate(cases, 1):
            print(f"[exécution {rep}/{args.repeat}, cas {i}/{len(cases)}] {case.id} : {case.question}", flush=True)
            session = session_id(case, run_tag)
            elapsed = run_openclaw(case, session, capture_root, args.timeout)
            calls, answer = openclaw_transcript(session, capture_root, defaults)
            if not calls and not answer:  # le silence n'est pas un échec du modèle : arrêter la mesure
                sys.exit(f"Session {session} sans appel ni réponse : vérifier LM Studio et le gateway.")
            adk = adk_rows[case.id]
            adk_executed, adk_proposed = adk_calls(adk)
            record = {
                "run_id": run_id, "repetition": rep, "case_id": case.id, "question": case.question,
                "adk_run_id": adk_run,
                "openclaw": {"elapsed_seconds": round(elapsed, 1), "tool_calls": calls, "final_answer": answer,
                             **grade(case, calls, answer, e2e)},
                "adk": {"elapsed_seconds": adk["elapsed_seconds"], "final_answer": adk["final_answer"],
                        "proposed_args_ok": grade(case, adk_proposed, "", e2e)["args_ok"],
                        **grade(case, adk_executed, adk["final_answer"], e2e)},
            }
            records.append(record)
            oc = record["openclaw"]
            print(f"    OpenClaw : réponse {'juste' if oc['answer_ok'] else 'FAUSSE'}, "
                  f"arguments {'conformes' if oc['args_ok'] else oc['wrong_args']}, {oc['elapsed_seconds']} s",
                  flush=True)

    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "openclaw_vs_adk.jsonl").open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    lines = report(records, run_id, capture_root)
    (RESULTS / "openclaw_vs_adk.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-2:]))
    print(f"Rapport : {RESULTS / 'openclaw_vs_adk.md'}")


def report(records: list[dict], run_id: str, capture_root) -> list[str]:
    """Par cas, réussites sur N exécutions ; puis le score de chaque exécution, pour juger de la variance."""
    reps = sorted({r.get("repetition", 1) for r in records})
    by_case: dict[str, list[dict]] = {}
    for r in records:
        by_case.setdefault(r["case_id"], []).append(r)

    def count(rows, agent, key):
        return f"{sum(r[agent][key] for r in rows)}/{len(rows)}"

    def per_rep(agent, key):
        return ", ".join(str(sum(r[agent][key] for r in records if r.get("repetition", 1) == rep)) for rep in reps)

    lines = [f"# OpenClaw contre ADK — {run_id}", "",
             f"Cas : {len(by_case)}, exécutions : {len(reps)}. Runs ADK : "
             f"{', '.join(sorted({r['adk_run_id'] for r in records}))}. Captures : {capture_root}", "",
             "| Cas | OpenClaw réponse | OpenClaw arguments | ADK réponse | ADK proposition Qwen "
             "| OpenClaw s (médiane) | ADK s (médiane) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for case_id, rows in by_case.items():
        wrong = [r["openclaw"]["wrong_args"] for r in rows if not r["openclaw"]["args_ok"]]
        lines.append(f"| {case_id} | {count(rows, 'openclaw', 'answer_ok')} | {count(rows, 'openclaw', 'args_ok')}"
                     f"{' ' + str(wrong[0]) if wrong else ''} | {count(rows, 'adk', 'answer_ok')} | "
                     f"{count(rows, 'adk', 'proposed_args_ok')} | "
                     f"{statistics.median(r['openclaw']['elapsed_seconds'] for r in rows)} | "
                     f"{statistics.median(r['adk']['elapsed_seconds'] for r in rows)} |")
    lines += ["", f"Réponses justes sur {len(by_case)}, par exécution : OpenClaw {per_rep('openclaw', 'answer_ok')} ; "
                  f"ADK {per_rep('adk', 'answer_ok')}.",
              f"Arguments exécutés conformes, par exécution : OpenClaw {per_rep('openclaw', 'args_ok')} ; "
              f"ADK {per_rep('adk', 'args_ok')} ; proposition Qwen conforme chez ADK : "
              f"{per_rep('adk', 'proposed_args_ok')}."]
    return lines


if __name__ == "__main__":
    main()
