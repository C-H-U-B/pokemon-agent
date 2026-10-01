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

        return "".join(
            part.text or ""
            for part in event.content.parts
        )

    return ""


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_can_call_local_qwen():
    """Smoke test ADK -> LiteLLM -> LM Studio -> Qwen."""

    events = asyncio.run(
        _run_agent("Réponds uniquement par ADK_OK.")
    )

    response_text = _final_response_text(events)

    assert "ADK_OK" in response_text


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_calls_pokemon_types_through_mcp():
    """ADK doit utiliser le tool MCP pokemon_types pour Pikachu."""

    events = asyncio.run(
        _run_agent("Quels sont les types de Pikachu ?")
    )

    tool_calls = []

    for event in events:
        if event.content is None:
            continue

        for part in event.content.parts:
            function_call = part.function_call

            if function_call is not None:
                tool_calls.append(function_call)

    assert tool_calls, (
        "Aucun appel de tool détecté : "
        "Qwen a peut-être répondu avec ses connaissances internes."
    )

    pokemon_types_calls = [
        call
        for call in tool_calls
        if call.name == "pokemon_types"
    ]

    assert pokemon_types_calls, (
        "L'agent a appelé un tool, mais pas pokemon_types."
    )

    call = pokemon_types_calls[0]

    assert call.args.get("pokemon", "").lower() == "pikachu"

    response_text = _final_response_text(events)

    assert response_text, "L'agent n'a produit aucune réponse finale."