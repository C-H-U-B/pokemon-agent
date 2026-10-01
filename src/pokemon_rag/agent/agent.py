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
        "Utilise les noms français des Pokémon, capacités et jeux lorsqu'ils "
        "existent, notamment les champs name_fr des outils. N'ajoute pas de "
        "traductions anglaises entre parenthèses sauf demande explicite. "
        "Les identifiers et version_group sont des clés techniques, pas des "
        "libellés à afficher : présente les jeux en français (par exemple "
        "Rubis Oméga / Saphir Alpha, Soleil / Lune, Ultra-Soleil / Ultra-Lune, "
        "Épée / Bouclier). Conserve les identifiants techniques dans les appels. "
        "Pour les CT sans jeu demandé, l'outil sélectionne le groupe de versions "
        "le plus récent disponible dans les données locales. Indique toujours "
        "dans la réponse le jeu renvoyé dans version_group, avec son nom français. "
        "Pour répondre aux questions Pokémon, utilise les outils MCP disponibles "
        "lorsqu'ils permettent d'obtenir l'information demandée, plutôt que de "
        "répondre à partir de tes connaissances internes. "
        "Choisis l'outil dont la fonction correspond le mieux à la question. "
        "Pour l'apparence, la description physique, le comportement, l'habitat, "
        "l'origine ou l'histoire d'un Pokémon, utilise pokemon_rag_search avec "
        "la question complète et le Pokémon ciblé. Par exemple, 'À quoi "
        "ressemble Bastiodon ?' demande une recherche documentaire, pas ses "
        "types. pokemon_types ne répond qu'aux questions de types ; les types, "
        "le numéro et les capacités ne sont pas des preuves d'apparence. "
        "Un appel réussi ne suffit pas : vérifie que les données retournées "
        "répondent réellement à la demande. Pour une description, utilise "
        "uniquement les détails présents dans les passages récupérés, cite "
        "leurs sources et n'invente aucun détail physique. Si les passages "
        "sont absents ou insuffisants, indique que la description demandée "
        "n'a pas pu être obtenue depuis les sources du projet. "
        "Respecte toutes les contraintes explicites données par l'utilisateur, "
        "notamment la forme du Pokémon, le jeu ou la version, et les niveaux. "
        "Si un appel d'outil est refusé parce qu'il ne permet pas de respecter "
        "une contrainte, utilise les informations de l'erreur pour choisir un "
        "outil compatible et réessayer. "
        "Utilise la recherche documentaire lorsque les outils structurés ne "
        "couvrent pas l'information demandée. "
        "Une erreur technique, une entrée introuvable, un résultat vide ou une "
        "valeur non renseignée ne prouvent pas un fait Pokémon. Après un échec, "
        "tu peux essayer un autre outil approprié, y compris la recherche "
        "documentaire si elle peut répondre sans perdre les contraintes. "
        "Ne complète jamais une donnée factuelle manquante depuis tes "
        "connaissances internes. Si les sources du projet ne permettent pas "
        "d'obtenir l'information, dis explicitement que tu n'as pas pu "
        "l'obtenir. Ne présente pas une erreur technique comme une absence "
        "de données ni un résultat vide comme une preuve de non-existence."
    ),
    tools=[
        pokemon_mcp,
    ],
    before_tool_callback=before_tool_guard,
)
