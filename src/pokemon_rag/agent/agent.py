"""Agent ADK minimal : Qwen local, sans outils ni accès aux données du projet."""

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm


LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
MODEL_NAME = "openai/qwen/qwen3-vl-8b"


model = LiteLlm(
    model=MODEL_NAME,
    # Paramètres explicites pour conserver l'endpoint local même si
    # l'environnement contient une configuration OpenAI différente.
    api_base=LM_STUDIO_BASE_URL,
    api_key="lm-studio",
)


root_agent = Agent(
    name="pokemon_agent",
    model=model,
    description="Agent Pokémon utilisant un modèle local via LM Studio.",
    instruction=(
        "Tu es un assistant Pokémon. "
        "Réponds en français de manière précise et concise."
    ),
)
