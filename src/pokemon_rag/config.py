import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Serveur de modèle compatible OpenAI : LM Studio local par défaut ; Ollama,
# un autre hôte ou une API distante se configurent par variables d'environnement.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen/qwen3-vl-8b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "lm-studio")

# Limite de sortie par appel de l'agent ADK. 1 024 convient au contexte de 16 384 tokens de Qwen local ;
# un modèle distant qui compte sa réflexion dans cette limite (Gemini) coupe la réponse visible avant.
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "1024"))

# Délai réseau par appel et reprises de transport du client LLM.
LLM_TIMEOUT_SECONDS = 120.0
LLM_MAX_RETRIES = 0

# Délai d'un appel d'outil MCP par l'agent ADK. La première recherche documentaire charge
# deux modèles et le corpus (environ une minute sur processeur) ; le défaut ADK est de 5 s.
MCP_TIMEOUT_SECONDS = 180.0

DATA_DIR = PROJECT_ROOT / "data"
CHROMA_PATH = PROJECT_ROOT / "chroma_db"

DB_PATH = DATA_DIR / "pokemon.db"
SPREADSHEET_PATH = DATA_DIR / "pokedex_particularites.xlsx"

POKEAPI_DIR = DATA_DIR / "pokeapi"
POKEAPI_RAW_DIR = POKEAPI_DIR / "raw"
POKEAPI_DB_PATH = POKEAPI_DIR / "pokeapi.db"

POKEPEDIA_DIR = DATA_DIR / "pokepedia"
POKEPEDIA_RAW_DIR = POKEPEDIA_DIR / "raw"
POKEPEDIA_CLEANED_DIR = POKEPEDIA_DIR / "cleaned"
