import asyncio
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pokemon_rag.mcp.server"],
    )

    start = time.perf_counter()

    async with stdio_client(server_params) as (read, write):
        connected = time.perf_counter()
        print(f"\nstdio_client: {connected - start:.3f}s")

        async with ClientSession(read, write) as session:
            before_init = time.perf_counter()

            result = await session.initialize()

            after_init = time.perf_counter()
            print(f"initialize: {after_init - before_init:.3f}s")
            print(f"total jusqu'à initialize: {after_init - start:.3f}s")
            print("INITIALIZED:", result)

            before_tools = time.perf_counter()

            tools = await session.list_tools()

            after_tools = time.perf_counter()
            print(f"list_tools: {after_tools - before_tools:.3f}s")
            print("TOOLS:", [tool.name for tool in tools.tools])


def test_mcp_server_stdio():
    asyncio.run(_main())