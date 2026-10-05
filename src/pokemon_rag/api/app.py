"""API HTTP au-dessus du moteur structuré.

Mêmes fonctions SQL que le serveur MCP : aucun modèle n'est appelé ici.
Lancement local : uvicorn pokemon_rag.api.app:app --reload
"""
from typing import Any

from fastapi import FastAPI, HTTPException

from pokemon_rag.structured.query_engine import get_pokemon_types

app = FastAPI(title="Pokémon RAG", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Indique que le service répond ; ne vérifie pas encore la base."""
    return {"status": "ok"}


@app.get("/pokemon/{name}/types")
def pokemon_types(name: str, form: str | None = None) -> dict[str, Any]:
    """Types d'un Pokémon nommé ; `form` est un paramètre de requête facultatif."""
    try:
        return get_pokemon_types(pokemon=name, form=form)
    except ValueError as exc:
        # Le moteur lève ValueError pour un nom ou une forme introuvable.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
