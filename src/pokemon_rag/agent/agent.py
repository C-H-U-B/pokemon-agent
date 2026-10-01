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
        "pokemon_evolutions",
        "pokemon_level_up_moves",
        "pokemon_move_learning_methods",
        "pokemon_machine_moves",
        "pokemon_types",
        "pokemon_pokedex_identity",
        "pokemon_signature_moves",
        "pokemon_rag_search",
    ],
)


root_agent = Agent(
    name="pokemon_agent",
    model=model,
    description="Agent Pokémon utilisant des données locales via MCP.",
    instruction=(
        "Tu es un assistant Pokémon. "
        "Réponds en français de manière précise et concise. "
        "Pour répondre aux questions Pokémon, utilise les outils MCP disponibles "
        "lorsqu'ils permettent d'obtenir l'information demandée, plutôt que de "
        "répondre à partir de tes connaissances internes. "
        "Choisis l'outil dont la fonction correspond le mieux à la question. "
        "Respecte toutes les contraintes explicites données par l'utilisateur, "
        "notamment la forme du Pokémon, le jeu ou la version, et les niveaux. "
        "Si un appel d'outil est refusé parce qu'il ne permet pas de respecter "
        "une contrainte, utilise les informations de l'erreur pour choisir un "
        "outil compatible et réessayer. "
        "Utilise la recherche documentaire lorsque les outils structurés ne "
        "couvrent pas l'information demandée."
    ),
    tools=[
        pokemon_mcp,
    ],
    before_tool_callback=before_tool_guard,
)
