"""Campagne E2E des questions de description : vrai agent, vrai Qwen, vraie recherche Poképédia.

Séparée de la campagne structurée : elle charge les modèles de recherche et vérifie autre chose,
le déroulement : recherche appelée, passages reçus, réponse rédigée ou abstention. Elle ne vérifie
pas que la réponse est fidèle aux passages : cela se juge en relisant le rapport.
"""
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from pokemon_rag.agent.agent import root_agent
from pokemon_rag.agent.context_budget import BUDGET_ABSTENTION, DOUBLE_REQUEST_REFUSAL, TOOL_FAILURE_ABSTENTION
from pokemon_rag.config import LLM_BASE_URL, LLM_MODEL

JSONL_PATH = Path(__file__).resolve().parents[2] / "test_results" / "adk_documentary_e2e.jsonl"
REPORT_PATH = JSONL_PATH.with_suffix(".md")
RUN_ID = datetime.now().astimezone().isoformat(timespec="seconds")
SEARCH = "pokemon_rag_search"


def write_report(run_id: str = RUN_ID) -> None:
    """Rapport lisible d'une exécution, réécrit après chaque cas : question, passages, réponse."""
    rows = [json.loads(line) for line in JSONL_PATH.read_text(encoding="utf-8").splitlines()]
    rows = [row for row in rows if row["run_id"] == run_id]
    if not rows:
        return
    lines = [f"# Campagne des descriptions — {run_id}", "",
             f"**Modèle :** {rows[0]['model']} sur {rows[0]['server']}  ",
             f"**Réussis :** {sum(row['passed'] for row in rows)} sur {len(rows)}", "",
             "> Un cas réussi signifie que la recherche a été appelée et qu'une réponse a été rédigée à partir "
             "de passages. La fidélité de la réponse aux passages se juge en les lisant ci-dessous.", ""]
    for row in rows:
        lines += [f"## {'✅' if row['passed'] else '❌'} {row['case_id']}", "",
                  f"**Question :** {row['question']}  ", f"**But :** {row['note']}  ",
                  f"**Durée :** {row['elapsed_seconds']:.0f} s", ""]
        for call in row["tool_calls"]:
            lines.append(f"- Appel : `{call['name']}` {json.dumps(call['args'], ensure_ascii=False)}")
        failed = [check["message"] for check in row["checks"] if not check["passed"]]
        if failed:
            lines.append(f"- **Contrôles en échec :** {' ; '.join(failed)}")
        lines += ["", "### Réponse", "", row["final_answer"] or "*(aucune)*", "", "### Ce que les outils ont renvoyé", ""]
        for response in row["tool_responses"]:
            data = response["response"] if isinstance(response["response"], dict) else {}
            if response["name"] == SEARCH and data.get("results"):
                for passage in data["results"]:
                    lines += [f"**Passage — {passage.get('source_file')} › {passage.get('section_path')}**", "",
                              "> " + str(passage.get("text", "")).replace("\n", "\n> "), ""]
            else:
                lines += [f"`{response['name']}` : `{json.dumps(data, ensure_ascii=False)[:600]}`", ""]
        lines += ["---", ""]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    note: str
    # Double demande (description et fait structuré) : refusée avant tout appel au modèle.
    refused: bool = False
    # Aucun passage n'existe : la réponse attendue est l'abstention déterministe.
    abstention: bool = False


CASES = [
    Case("appearance-lowercase", "à quoi ressemble sovkipou ?",
         "Nom en minuscules : le filtre de la recherche doit retrouver le nom indexé."),
    Case("describe-tutafeh", "Décris Tutafeh",
         "Régression : la description était rédigée sans appeler la recherche documentaire."),
    Case("habitat-bacabouh", "Quel est l'habitat de Bacabouh ?",
         "Autre mot de description ; la réponse doit s'appuyer sur des passages."),
    Case("double-request-trepassable", "Décris Trépassable et donne ses types",
         "Double demande : refusée avec une consigne claire, aucun outil appelé, aucun type inventé.",
         refused=True),
    Case("unknown-pokemon", "Décris Fauxkémon",
         "Aucun passage : abstention, jamais une description inventée.", abstention=True),
]


async def _ask(question: str) -> tuple[list, float]:
    runner = InMemoryRunner(agent=root_agent)
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="documentary_e2e")
    start = time.perf_counter()
    try:
        events = [event async for event in runner.run_async(
            user_id="documentary_e2e", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]))]
        return events, time.perf_counter() - start
    finally:
        await runner.close()


def _parts(events):
    return [part for event in events for part in (event.content.parts if event.content else [])]


def _checks(case: Case, calls: list[dict], responses: list[dict], answer: str) -> list[tuple[bool, str]]:
    passages = [r for r in responses if r["name"] == SEARCH and r["response"].get("results")]
    if case.refused:
        return [(answer == DOUBLE_REQUEST_REFUSAL, "double demande refusée"), (not calls, "aucun outil appelé")]
    checks = [(answer != BUDGET_ABSTENTION, "pas d'abstention de budget")]
    if case.abstention:
        # Le contrat porte sur la réponse : que le modèle ait cherché ou non, il ne doit rien inventer.
        return checks + [(not passages, "aucun passage trouvé"),
                         (answer == TOOL_FAILURE_ABSTENTION, "abstention déterministe")]
    checks += [(any(call["name"] == SEARCH for call in calls), "recherche documentaire appelée"),
               (bool(passages), "au moins un passage trouvé"),
               (bool(answer) and answer != TOOL_FAILURE_ABSTENTION, "réponse rédigée à partir des passages")]
    return checks


@pytest.mark.models
@pytest.mark.real_data
@pytest.mark.llm
@pytest.mark.long
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_documentary_e2e(case):
    print(f"\n→ en cours: {case.id}", flush=True)
    events, elapsed = asyncio.run(_ask(case.question))
    parts = _parts(events)
    calls = [{"name": part.function_call.name, "args": dict(part.function_call.args or {})}
             for part in parts if part.function_call]
    responses = [{"name": part.function_response.name, "response": part.function_response.response}
                 for part in parts if part.function_response]
    answer = next(("".join(part.text or "" for part in event.content.parts).strip()
                   for event in reversed(events) if event.is_final_response() and event.content), "")
    checks = _checks(case, calls, responses, answer)
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps({
            "run_id": RUN_ID, "model": LLM_MODEL, "server": LLM_BASE_URL, "case_id": case.id,
            "question": case.question, "note": case.note, "elapsed_seconds": round(elapsed, 3),
            "tool_calls": calls, "tool_responses": responses, "final_answer": answer,
            "checks": [{"passed": ok, "message": message} for ok, message in checks],
            "passed": all(ok for ok, _ in checks)}, ensure_ascii=False, default=repr) + "\n")
    write_report()
    print(f"terminé: {case.id} ({elapsed:.0f} s) — rapport : {REPORT_PATH}", flush=True)
    failed = [message for ok, message in checks if not ok]
    assert not failed, f"{case.id} : {failed}\nRéponse : {answer[:300]}"
