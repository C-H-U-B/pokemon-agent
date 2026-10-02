import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from pokemon_rag.agent.agent import root_agent


RESULTS_DIR = Path(__file__).resolve().parents[2] / "test_results"
RESULTS_PATH = RESULTS_DIR / "adk_structured_search_e2e.jsonl"


async def _run_agent(prompt: str):
    """Exécute une requête réelle contre l'agent ADK local."""
    runner = InMemoryRunner(agent=root_agent)

    session = await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="test_structured_search_e2e",
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )

    events = []
    start = time.perf_counter()

    async for event in runner.run_async(
        user_id="test_structured_search_e2e",
        session_id=session.id,
        new_message=message,
    ):
        events.append(event)

    elapsed = time.perf_counter() - start
    return events, elapsed


def _final_response_text(events) -> str:
    """Extrait le texte de la réponse finale ADK."""
    for event in reversed(events):
        if not event.is_final_response() or event.content is None:
            continue

        return "".join(
            part.text or ""
            for part in event.content.parts
        ).strip()

    return ""


def _tool_calls(events) -> list[dict]:
    """Extrait les vrais function calls ADK sous une forme sérialisable."""
    calls = []

    for event in events:
        if event.content is None:
            continue

        for part in event.content.parts:
            if part.function_call is None:
                continue

            calls.append(
                {
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args or {}),
                }
            )

    return calls


def _tool_responses(events) -> list[dict]:
    """Extrait les vrais function responses ADK sous une forme sérialisable."""
    responses = []

    for event in events:
        if event.content is None:
            continue

        for part in event.content.parts:
            if part.function_response is None:
                continue

            response = part.function_response
            responses.append(
                {
                    "name": response.name,
                    "response": response.response,
                }
            )

    return responses


def _json_safe(value):
    """Convertit récursivement les objets ADK éventuels en valeurs JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())

    return repr(value)


def _save_run(
    *,
    question: str,
    elapsed_seconds: float,
    tool_calls: list[dict],
    tool_responses: list[dict],
    final_answer: str,
    passed: bool,
    error: str | None = None,
) -> None:
    """Ajoute le détail d'une exécution au journal JSONL."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "question": question,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "tool_calls": _json_safe(tool_calls),
        "tool_responses": _json_safe(tool_responses),
        "final_answer": final_answer,
        "passed": passed,
        "error": error,
    }

    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False)
        handle.write("\n")


def _pokemon_search_call(tool_calls: list[dict]) -> dict:
    calls = [
        call
        for call in tool_calls
        if call["name"] == "pokemon_search"
    ]

    assert calls, (
        "Qwen n'a pas appelé pokemon_search. "
        f"Tools observés : {[call['name'] for call in tool_calls]}"
    )

    return calls[0]


def _assert_required_args(call: dict, expected_args: dict) -> None:
    args = call["args"]

    for key, expected in expected_args.items():
        actual = args.get(key)
        assert actual == expected, (
            f"Argument incorrect pour {key!r}: "
            f"attendu={expected!r}, obtenu={actual!r}. "
            f"Arguments complets={args!r}"
        )


def _find_search_response(tool_responses: list[dict]) -> dict:
    responses = [
        response
        for response in tool_responses
        if response["name"] == "pokemon_search"
    ]

    assert responses, (
        "pokemon_search a été appelé mais aucune function_response "
        "correspondante n'a été observée."
    )

    raw = responses[-1]["response"]

    # ADK/MCP peut envelopper le résultat dans différentes structures.
    if isinstance(raw, dict):
        for key in ("result", "data", "content"):
            candidate = raw.get(key)
            if isinstance(candidate, dict):
                return candidate
        return raw

    raise AssertionError(
        "Format inattendu de la réponse pokemon_search : "
        f"{type(raw).__name__}: {raw!r}"
    )


def _response_contains_name(response: dict, expected_name: str) -> bool:
    """Recherche un nom dans la réponse structurée sans dépendre du schéma exact."""
    serialized = json.dumps(
        _json_safe(response),
        ensure_ascii=False,
    ).casefold()

    return expected_name.casefold() in serialized


def _response_contains_value(response: dict, expected_value: int) -> bool:
    """Vérification souple de la valeur dans le résultat structuré."""
    def walk(value):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return value == expected_value
        if isinstance(value, dict):
            return any(walk(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(walk(item) for item in value)
        return False

    return walk(response)


CASES = [
    pytest.param(
        "Quel est le Pokémon légendaire le plus rapide ?",
        {
            "legendary": True,
            "sort_by": "speed",
            "sort_order": "desc",
            "best_only": True,
        },
        ["Regieleki"],
        200,
        id="legendary-fastest",
    ),
    pytest.param(
        "Quel est le Pokémon Feu avec le plus d'Attaque ?",
        {
            "sort_by": "attack",
            "sort_order": "desc",
            "best_only": True,
        },
        ["Darumacho"],
        140,
        id="fire-highest-attack",
    ),
    pytest.param(
        "Quels sont les Pokémon Méga les plus lents ?",
        {
            "form_category": "mega",
            "sort_by": "speed",
            "sort_order": "asc",
            "best_only": True,
        },
        ["Méga-Ténéfix", "Méga-Camérupt"],
        20,
        id="mega-slowest-tie",
    ),
    pytest.param(
        "Quelle Méga a le plus d'Attaque ?",
        {
            "form_category": "mega",
            "sort_by": "attack",
            "sort_order": "desc",
            "best_only": True,
        },
        ["Méga-Mewtwo X"],
        190,
        id="mega-highest-attack",
    ),
]


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
@pytest.mark.parametrize(
    "question,expected_args,expected_names,expected_value",
    CASES,
)
def test_adk_structured_search_superlatives(
    question,
    expected_args,
    expected_names,
    expected_value,
):
    """E2E réel : français -> Qwen -> MCP -> SQL -> Qwen."""
    events = []
    elapsed = 0.0
    tool_calls = []
    tool_responses = []
    final_answer = ""

    try:
        events, elapsed = asyncio.run(_run_agent(question))
        tool_calls = _tool_calls(events)
        tool_responses = _tool_responses(events)
        final_answer = _final_response_text(events)

        call = _pokemon_search_call(tool_calls)
        _assert_required_args(call, expected_args)

        # Le cas Feu doit réellement préserver le filtre de type.
        if "Feu" in question:
            types_arg = call["args"].get("types")
            assert isinstance(types_arg, list), (
                f"Le filtre types doit être une liste, obtenu={types_arg!r}"
            )
            assert len(types_arg) == 1, (
                f"Un seul type Feu était demandé, obtenu={types_arg!r}"
            )
            assert str(types_arg[0]).casefold() in {"feu", "fire"}, (
                f"Le filtre Feu a été perdu ou mal traduit : {types_arg!r}"
            )

        response = _find_search_response(tool_responses)

        for expected_name in expected_names:
            assert _response_contains_name(response, expected_name), (
                f"{expected_name!r} absent du résultat structuré pokemon_search."
            )

        assert _response_contains_value(response, expected_value), (
            f"La valeur attendue {expected_value} est absente "
            "du résultat structuré pokemon_search."
        )

        assert final_answer, "Qwen n'a produit aucune réponse finale."

        normalized_answer = final_answer.casefold()
        for expected_name in expected_names:
            assert expected_name.casefold() in normalized_answer, (
                f"{expected_name!r} est présent dans le résultat outil "
                "mais absent de la réponse finale de Qwen. "
                f"Réponse={final_answer!r}"
            )

        assert str(expected_value) in final_answer, (
            f"La valeur {expected_value} est présente dans le résultat outil "
            "mais absente de la réponse finale de Qwen. "
            f"Réponse={final_answer!r}"
        )

    except Exception as exc:
        _save_run(
            question=question,
            elapsed_seconds=elapsed,
            tool_calls=tool_calls,
            tool_responses=tool_responses,
            final_answer=final_answer,
            passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    _save_run(
        question=question,
        elapsed_seconds=elapsed,
        tool_calls=tool_calls,
        tool_responses=tool_responses,
        final_answer=final_answer,
        passed=True,
    )


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_structured_search_top_five_speed():
    """E2E d'un top N : vérifie le routage et conserve la réponse pour revue."""
    question = "Quels sont les 5 Pokémon les plus rapides ?"

    events = []
    elapsed = 0.0
    tool_calls = []
    tool_responses = []
    final_answer = ""

    try:
        events, elapsed = asyncio.run(_run_agent(question))
        tool_calls = _tool_calls(events)
        tool_responses = _tool_responses(events)
        final_answer = _final_response_text(events)

        call = _pokemon_search_call(tool_calls)
        _assert_required_args(
            call,
            {
                "sort_by": "speed",
                "sort_order": "desc",
                "best_only": False,
                "limit": 5,
            },
        )

        response = _find_search_response(tool_responses)

        assert response, "pokemon_search a renvoyé un résultat vide inattendu."
        assert final_answer, "Qwen n'a produit aucune réponse finale."

    except Exception as exc:
        _save_run(
            question=question,
            elapsed_seconds=elapsed,
            tool_calls=tool_calls,
            tool_responses=tool_responses,
            final_answer=final_answer,
            passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    _save_run(
        question=question,
        elapsed_seconds=elapsed,
        tool_calls=tool_calls,
        tool_responses=tool_responses,
        final_answer=final_answer,
        passed=True,
    )
