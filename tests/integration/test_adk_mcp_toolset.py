import asyncio

import pytest
from google.adk.tools.mcp_tool import McpToolset

from pokemon_rag.agent.agent import pokemon_mcp


async def _get_mcp_tools():
    """Charge les tools exposés à ADK par le serveur MCP."""
    # Une session indépendante par boucle asyncio, fermée avant sa destruction.
    toolset = McpToolset(
        connection_params=pokemon_mcp.connection_params,
        tool_filter=pokemon_mcp.tool_filter,
    )
    try:
        return await toolset.get_tools()
    finally:
        await toolset.close()


@pytest.mark.integration
def test_adk_mcp_toolset_exposes_expected_tools():
    """ADK doit exposer exactement les tools MCP autorisés à l'agent."""

    tools = asyncio.run(_get_mcp_tools())

    tool_names = {tool.name for tool in tools}

    expected_tools = {
        "pokemon_evolutions",
        "pokemon_level_up_moves",
        "pokemon_move_learning_methods",
        "pokemon_machine_moves",
        "pokemon_types",
        "pokemon_pokedex_identity",
        "pokemon_signature_moves",
        "pokemon_rag_search",
    }

    assert tool_names == expected_tools, (
        "Les tools MCP exposés à l'agent ne correspondent pas "
        "à l'interface attendue. "
        f"Tools découverts : {sorted(tool_names)}"
    )