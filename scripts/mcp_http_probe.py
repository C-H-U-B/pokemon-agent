"""Sonde d'un serveur MCP servi en HTTP (conteneur local ou Cloud Run), sans LLM.

Mesure la connexion, la liste des outils, un appel SQL et un appel de recherche documentaire,
dont le premier attend le chargement des modèles quand l'instance vient de démarrer.

    python scripts/mcp_http_probe.py http://127.0.0.1:8080/mcp
"""

from __future__ import annotations

import asyncio
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


async def probe(url: str) -> None:
    start = time.perf_counter()

    def step(label: str) -> None:
        print(f"{time.perf_counter() - start:7.1f} s  {label}", flush=True)

    # La façade OAuth du serveur accepte tout jeton (src/pokemon_rag/mcp/open_oauth.py).
    client = create_mcp_http_client(headers={"Authorization": "Bearer sonde"})
    async with streamable_http_client(url, http_client=client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            step("session initialisée")
            tools = await session.list_tools()
            step(f"{len(tools.tools)} outils")
            stats = await session.call_tool("pokemon_base_stats", arguments={"pokemon": "Dracolosse"})
            step(f"pokemon_base_stats : {'erreur' if stats.is_error else 'ok'}")
            for attempt in (1, 2):
                rag = await session.call_tool(
                    "pokemon_rag_search", arguments={"question": "anecdote sur Ronflex", "pokemon": "Ronflex"})
                found = len((rag.structured_content or {}).get("results", []))
                step(f"pokemon_rag_search n°{attempt} : {'erreur' if rag.is_error else f'{found} passages'}")


if __name__ == "__main__":
    asyncio.run(probe(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/mcp"))
