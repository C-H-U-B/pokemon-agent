import os
import sys

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from pokemon_rag.agent.tool_guard import before_tool_guard


LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
MODEL_NAME = "openai/qwen/qwen3-vl-8b"


# LiteLLM utilise l'API OpenAI-compatible exposée par LM Studio.
os.environ.setdefault("OPENAI_API_KEY", "lm-studio")
os.environ.setdefault("OPENAI_API_BASE", LM_STUDIO_BASE_URL)


model = LiteLlm(
    model=MODEL_NAME,
)


pokemon_mcp = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "pokemon_rag.mcp.server",
            ],
        ),
    ),
    tool_filter=[
        "pokemon_types",
    ],
)


root_agent = Agent(
    name="pokemon_agent",
    model=model,
    description="Agent Pokémon utilisant des données locales via MCP.",
    instruction=(
        "Tu es un assistant Pokémon. "
        "Réponds en français de manière précise et concise. "
        "Lorsque la question concerne les types d'un Pokémon, "
        "utilise l'outil pokemon_types au lieu de répondre à partir "
        "de tes connaissances internes."
    ),
    tools=[
        pokemon_mcp,
    ],
    before_tool_callback=before_tool_guard,
)