import asyncio
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _initialize_and_list_tools():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pokemon_rag.mcp.server"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            result = await session.initialize()
            assert result.protocol_version
            assert result.capabilities.tools is not None
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            assert "pokemon_types" in names
            assert "pokemon_rag_search" in names
            assert len(names) == len(set(names))


@pytest.mark.integration
def test_mcp_server_stdio():
    """Initialise le vrai serveur et découvre ses outils, sans les exécuter."""
    asyncio.run(_initialize_and_list_tools())
