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
    "pokemon_search",
    "pokemon_moves",
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

            schema = tools["pokemon_search"].input_schema["properties"]
            assert set(schema["sort_by"]["enum"]) == {
                "national_number", "hp", "attack", "defense", "special-attack",
                "special-defense", "speed", "base-stat-total"}
            assert set(schema["sort_order"]["enum"]) == {"asc", "desc"}
            assert "ex aequo" in schema["best_only"]["description"]
            mega = await session.call_tool("pokemon_search", arguments={
                "form_category":"mega", "sort_by":"attack", "sort_order":"desc", "best_only":True})
            assert not mega.is_error
            assert mega.structured_content["results"][0]["name_fr"] == "Méga-Mewtwo X"
            assert mega.structured_content["best_value"] == 190
            total = await session.call_tool("pokemon_search", arguments={
                "types":["Eau","Vol"], "type_match":"exact", "sort_by":"base-stat-total",
                "sort_order":"desc", "best_only":True})
            assert not total.is_error and total.structured_content["best_value"] == 540
            tied = await session.call_tool("pokemon_search", arguments={
                "form_category":"mega", "sort_by":"speed", "sort_order":"asc", "best_only":True, "limit":1})
            assert not tied.is_error and tied.structured_content["tie_count"] == 2
            assert tied.structured_content["returned_count"] == 1
            for invalid_args in ({"sort_by":"sql"}, {"sort_order":"sideways"}, {"form_category":"unknown"}):
                assert (await session.call_tool("pokemon_search", arguments=invalid_args)).is_error

            search = await session.call_tool("pokemon_search", arguments={"pokedex_number": 369})
            assert not search.is_error
            assert search.structured_content["results"][0]["name_fr"] == "Relicanth"
            moves = await session.call_tool("pokemon_moves", arguments={
                "pokemon": "Scarhino", "version_group": "scarlet-violet",
                "damage_class": "physical", "min_power": 100, "limit": 1})
            assert not moves.is_error
            assert moves.structured_content["results"][0]["power"] >= 100
            assert moves.structured_content["truncated"]
            invalid = await session.call_tool("pokemon_search", arguments={"types": ["inconnu"]})
            assert invalid.is_error

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
            nigirigon = await session.call_tool(
                "pokemon_types", arguments={"pokemon": "Nigirigon"}
            )
            assert not nigirigon.is_error
            assert nigirigon.structured_content["rows"][0]["type_1_fr"] == "Dragon"
            assert nigirigon.structured_content["rows"][0]["type_2_fr"] == "Eau"

            missing = await session.call_tool(
                "pokemon_types", arguments={"pokemon": "Espèce inexistante"}
            )
            assert missing.is_error

            assert data["operation"] == "get_pokemon_types"
            assert data["pokemon"].casefold() == "pikachu"
            assert data["count"] == len(data["rows"]) == 1

            row = data["rows"][0]

            assert row["name_fr"].casefold() == "pikachu"
            assert row["type_1_fr"] == "Électrik"
            assert row["type_2_fr"] is None
