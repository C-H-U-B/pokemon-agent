import asyncio

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from pokemon_rag.agent.agent import root_agent


async def _run_agent(prompt: str):
    """Exécute une requête réelle contre l'agent ADK local."""
    runner = InMemoryRunner(agent=root_agent)

    session = await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="test_user",
    )

    message = types.Content(
        role="user",
        parts=[
            types.Part(text=prompt),
        ],
    )

    events = []

    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=message,
    ):
        events.append(event)

    return events


def _final_response_text(events) -> str:
    """Extrait le texte de la réponse finale ADK."""
    for event in reversed(events):
        if not event.is_final_response():
            continue

        if event.content is None:
            continue

        return "".join(part.text or "" for part in event.content.parts)

    return ""


def _tool_calls(events):
    """Extrait tous les function calls produits pendant une exécution ADK."""
    calls = []

    for event in events:
        if event.content is None:
            continue

        for part in event.content.parts:
            if part.function_call is not None:
                calls.append(part.function_call)

    return calls


def _assert_tool_called(events, tool_name: str):
    """Vérifie qu'un tool précis a été appelé et retourne son premier appel."""
    calls = _tool_calls(events)

    assert calls, (
        "Aucun appel de tool détecté : "
        "Qwen a peut-être répondu avec ses connaissances internes."
    )

    matching_calls = [call for call in calls if call.name == tool_name]

    assert matching_calls, (
        f"L'agent n'a pas appelé {tool_name}. "
        f"Tools appelés : {[call.name for call in calls]}"
    )

    return matching_calls[0]


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_can_call_local_qwen():
    """Smoke test ADK -> LiteLLM -> LM Studio -> Qwen."""
    events = asyncio.run(_run_agent("Réponds uniquement par ADK_OK."))

    response_text = _final_response_text(events)

    assert "ADK_OK" in response_text


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_routes_type_question():
    """Une question de type doit utiliser pokemon_types."""
    events = asyncio.run(_run_agent("Quels sont les types de Hexagel ?"))

    call = _assert_tool_called(
        events,
        "pokemon_types",
    )

    assert call.args.get("pokemon", "").lower() == "hexagel"

    assert _final_response_text(events)


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_routes_pokedex_identity_question():
    """Une question d'identité Pokédex doit utiliser le tool structuré."""
    events = asyncio.run(_run_agent("Quel est le numéro national de Sinistrail ?"))

    call = _assert_tool_called(
        events,
        "pokemon_pokedex_identity",
    )

    assert call.args.get("pokemon", "").lower() == "sinistrail"

    assert _final_response_text(events)


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_routes_machine_moves_with_version():
    """Une question de CT avec jeu explicite doit utiliser le tool adapté."""
    events = asyncio.run(
        _run_agent(
            "Quelles CT Gouroutan peut-il apprendre dans Pokémon Soleil et Lune ?"
        )
    )

    call = _assert_tool_called(
        events,
        "pokemon_machine_moves",
    )

    assert call.args.get("pokemon", "").lower() == "gouroutan"
    assert call.args.get("version_group") == "sun-moon"

    assert _final_response_text(events)


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_routes_level_up_moves_with_level_range():
    """Une plage de niveaux doit être préservée dans le tool call."""
    events = asyncio.run(
        _run_agent("Quelles capacités Opermine apprend-il entre les niveaux 10 et 25 ?")
    )

    call = _assert_tool_called(
        events,
        "pokemon_level_up_moves",
    )

    assert call.args.get("pokemon", "").lower() == "opermine"
    assert call.args.get("min_level") == 10
    assert call.args.get("max_level") == 25

    assert _final_response_text(events)
