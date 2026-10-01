from __future__ import annotations

import asyncio
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_MODULE = "pokemon_rag.mcp.server"
EXPECTED_TOOLS = {
    "pokemon_evolutions",
    "pokemon_level_up_moves",
    "pokemon_move_learning_methods",
    "pokemon_machine_moves",
    "pokemon_types",
    "pokemon_pokedex_identity",
    "pokemon_signature_moves",
    "pokemon_rag_search",
}


@pytest.mark.real_data
def test_mcp_server_discovers_tools_and_executes_real_structured_tool() -> None:
    """Valide le serveur MCP réel via stdio, sans LLM ni mocks."""
    asyncio.run(_check_server())


async def _check_server() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tools = {tool.name: tool for tool in tools_result.tools}

            assert set(tools) == EXPECTED_TOOLS

            pokemon_types = tools["pokemon_types"]
            assert pokemon_types.input_schema["type"] == "object"
            assert "pokemon" in pokemon_types.input_schema["properties"]
            assert "pokemon" in pokemon_types.input_schema["required"]

            result = await session.call_tool(
                "pokemon_types",
                arguments={"pokemon": "Pikachu"},
            )

            assert not result.is_error
            assert result.structured_content is not None

            data = result.structured_content

            assert data["operation"] == "get_pokemon_types"
            assert data["pokemon"].casefold() == "pikachu"
            assert data["count"] == len(data["rows"]) == 1

            row = data["rows"][0]

            assert row["name_fr"].casefold() == "pikachu"
            assert row["type_1_fr"] == "Électrik"
            assert row["type_2_fr"] is None
