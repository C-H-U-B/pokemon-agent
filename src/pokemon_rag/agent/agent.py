import os
import sys

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from pokemon_rag.agent.tool_guard import before_tool_guard
from pokemon_rag.agent.context_budget import before_model_budget, after_tool_budget


AGENT_INSTRUCTION = """Réponds en français avec les seuls faits demandés et prouvés par les outils. Sans preuve : information indisponible, jamais de mémoire.
Faits structurés : outils SQL. Apparence, comportement, habitat, origine, histoire : pokemon_rag_search ; cite les sources. Types et identité ne prouvent pas une description.
Listes : pokemon_search ; capacités : pokemon_moves. Numéro fourni : pokemon_search(pokedex_number=...), sans deviner d'espèce ; identité : nom vers numéro. Vérifie le numéro rendu. Types requis : type_match=all.
Classements : tri SQL, sans calcul ni filtre du modèle. Superlatif : best_only=true, signale tie/tie_count ; top N : best_only=false, limit=N. Toutes les Méga : form_category=mega. Base stats seulement, talents indisponibles.
Préserve forme, jeu et niveau ; après refus, suis l'appel compatible du guard. Sans forme : défaut ; sans jeu : dernier movepool disponible, nomme le jeu en français. Propriétés des capacités actuelles.
Reprends name_fr dans l'ordre, sans nom anglais, génération, classification ou exemple non demandé. Un nom de capacité exige pokemon_moves.
Compte avec total_count ; signale truncated/context_truncated et le total. Filtres et petites pages. Couverture incomplète : avertissement bref sans exceptions. Erreur ou movepool_available=false : indisponible, pas impossible à apprendre.
"""


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
        "pokemon_search",
        "pokemon_moves",
    ],
)


root_agent = Agent(
    name="pokemon_agent",
    model=model,
    description="Agent Pokémon utilisant des données locales via MCP.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        pokemon_mcp,
    ],
    before_tool_callback=before_tool_guard,
    after_tool_callback=after_tool_budget,
    before_model_callback=before_model_budget,
)
