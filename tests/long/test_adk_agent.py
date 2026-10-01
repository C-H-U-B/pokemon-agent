import asyncio

import pytest

from google.adk.runners import InMemoryRunner
from google.genai import types

from pokemon_rag.agent.agent import root_agent


@pytest.mark.models
@pytest.mark.llm
@pytest.mark.long
def test_adk_agent_can_call_local_qwen():
    """Smoke test: ADK can call the local Qwen model through LM Studio."""
    asyncio.run(_call_local_qwen())


async def _call_local_qwen():
    runner = InMemoryRunner(agent=root_agent)

    session = await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="test_user",
    )

    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text="Réponds uniquement par ADK_OK."
            )
        ],
    )

    final_response = None

    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response():
            final_response = event.content

    assert final_response is not None

    response_text = "".join(
        part.text or ""
        for part in final_response.parts
    )

    assert "ADK_OK" in response_text
