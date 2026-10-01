import asyncio

import pytest
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from pokemon_rag.agent.agent import MODEL_NAME


def echo_tool(text: str) -> dict:
    """Retourne exactement le texte fourni.

    Args:
        text: Texte à retourner.
    """
    return {"text": text}


async def _run_agent():
    agent = Agent(
        name="tool_call_test_agent",
        model=LiteLlm(model=MODEL_NAME),
        instruction=(
            "Utilise obligatoirement l'outil echo_tool pour répondre "
            "à la demande de l'utilisateur."
        ),
        tools=[echo_tool],
    )

    runner = InMemoryRunner(agent=agent)

    session = await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="test_user",
    )

    message = types.Content(
        role="user",
        parts=[
            types.Part(text="Utilise echo_tool avec le texte TEST_TOOL.")
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


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_litellm_tool_calling():
    events = asyncio.run(_run_agent())

    tool_calls = []

    for event in events:
        if event.content is None:
            continue

        for part in event.content.parts:
            if part.function_call is not None:
                tool_calls.append(part.function_call)

    assert tool_calls, (
        "ADK/LiteLLM n'a produit aucun vrai function call."
    )

    echo_calls = [
        call
        for call in tool_calls
        if call.name == "echo_tool"
    ]

    assert echo_calls, (
        "Un function call a été produit, mais pas vers echo_tool."
    )

    assert echo_calls[0].args.get("text") == "TEST_TOOL"