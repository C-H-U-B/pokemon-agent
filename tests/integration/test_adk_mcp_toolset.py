import asyncio

import pytest

from pokemon_rag.agent.agent import pokemon_mcp


async def _get_mcp_tools():
    """Charge les tools exposés à ADK par le serveur MCP."""
    return await pokemon_mcp.get_tools()


@pytest.mark.integration
def test_adk_mcp_toolset_discovers_pokemon_types():
    """ADK doit découvrir pokemon_types depuis le serveur MCP."""

    tools = asyncio.run(_get_mcp_tools())

    tool_names = [tool.name for tool in tools]

    assert "pokemon_types" in tool_names, (
        "pokemon_types n'a pas été découvert par McpToolset. "
        f"Tools découverts : {tool_names}"
    )


@pytest.mark.integration
def test_adk_mcp_tool_filter_exposes_only_pokemon_types():
    """Le filtre ADK doit masquer les autres tools MCP."""

    tools = asyncio.run(_get_mcp_tools())

    tool_names = [tool.name for tool in tools]

    assert tool_names == ["pokemon_types"], (
        "Le tool_filter n'a pas produit l'ensemble attendu. "
        f"Tools exposés : {tool_names}"
    )