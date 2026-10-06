"""Campagne E2E des questions de description : vrai agent, vrai Qwen, vraie recherche Poképédia.

Séparée de la campagne structurée : elle charge les modèles de recherche et vérifie autre chose,
que la description vient de passages réellement trouvés et jamais de la mémoire du modèle.
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
from pokemon_rag.agent.context_budget import BUDGET_ABSTENTION, TOOL_FAILURE_ABSTENTION
from pokemon_rag.config import LLM_BASE_URL, LLM_MODEL

JSONL_PATH = Path(__file__).resolve().parents[2] / "test_results" / "adk_documentary_e2e.jsonl"
RUN_ID = datetime.now().astimezone().isoformat(timespec="seconds")
SEARCH = "pokemon_rag_search"


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    note: str
    # Outils structurés qui doivent aussi avoir répondu (question composée).
    other_tools: tuple[str, ...] = ()
    # Aucun passage n'existe : la réponse attendue est l'abstention déterministe.
    abstention: bool = False


CASES = [
    Case("appearance-lowercase", "à quoi ressemble sovkipou ?",
         "Nom en minuscules : le filtre de la recherche doit retrouver le nom indexé."),
    Case("describe-tutafeh", "Décris Tutafeh",
         "Régression : la description était rédigée sans appeler la recherche documentaire."),
    Case("habitat-bacabouh", "Quel est l'habitat de Bacabouh ?",
         "Autre mot de description ; la réponse doit s'appuyer sur des passages."),
    Case("compound-trepassable", "Décris Trépassable et donne ses types",
         "Question composée : recherche documentaire et outil structuré, sans abstention.",
         other_tools=("pokemon_types",)),
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
    checks = [(any(call["name"] == SEARCH for call in calls), "recherche documentaire appelée"),
              (answer != BUDGET_ABSTENTION, "pas d'abstention de budget")]
    if case.abstention:
        return checks + [(not passages, "aucun passage trouvé"),
                         (answer == TOOL_FAILURE_ABSTENTION, "abstention déterministe")]
    checks += [(bool(passages), "au moins un passage trouvé"),
               (bool(answer) and answer != TOOL_FAILURE_ABSTENTION, "réponse rédigée à partir des passages")]
    for tool in case.other_tools:
        checks.append((any(r["name"] == tool and not r["response"].get("error") for r in responses),
                       f"outil structuré {tool} a répondu"))
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
    print(f"terminé: {case.id} ({elapsed:.0f} s)", flush=True)
    failed = [message for ok, message in checks if not ok]
    assert not failed, f"{case.id} : {failed}\nRéponse : {answer[:300]}"
