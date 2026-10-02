import os
import sys

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from pokemon_rag.agent.tool_guard import before_tool_guard
from pokemon_rag.agent.context_budget import before_model_budget, after_tool_budget


AGENT_INSTRUCTION = """Réponds en français avec les seuls faits demandés et prouvés par les outils, jamais de mémoire. Valeur/condition absente : inconnue ; n'invente aucun niveau, jeu, type ou capacité. Erreur technique ≠ Pokémon absent.
Faits structurés : outils SQL. Apparence, comportement, habitat, origine, histoire : pokemon_rag_search ; cite les sources. Types et identité ne prouvent pas une description.
Listes : pokemon_search ; capacités : pokemon_moves. Nom explicite : préserve ce Pokémon. Nom → numéro : pokemon_pokedex_identity(pokemon=nom). Numéro → Pokémon : pokemon_search(pokedex_number=N). Types requis : type_match=all. Fabuleux : mythical=true ; légendaire : legendary=true, filtres indépendants. Liste simple : best_only=false.
Classements : sort_by=hp/attack/defense/special-attack/special-defense/speed/base-stat-total pour PV/Attaque/Défense/Attaque Spéciale/Défense Spéciale/Vitesse/total. Maximum/rapide : desc ; minimum/lent : asc. Sans quantité, superlatif singulier OU pluriel : best_only=true, tous les ex aequo. Quantité N : best_only=false, limit=N. Méga : form_category=mega. Cite chaque base_stat_value avec stat_name_fr ; best_value pour le seuil, tie/tie_count pour les égalités. Base stats seulement, talents indisponibles.
Préserve forme, jeu et niveau ; après refus, suis l'appel compatible du guard. Sans forme : défaut ; sans jeu : dernier movepool disponible, nomme le jeu en français. Propriétés des capacités actuelles.
Reprends les champs français dans l'ordre, Pokémon et capacités compris. Jamais de nom anglais entre parenthèses sauf demande explicite d'anglais ; pas de génération, classification ou exemple non demandé. Un nom de capacité exige un outil de capacités.
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
