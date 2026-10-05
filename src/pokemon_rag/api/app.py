"""API HTTP au-dessus du moteur structuré.

Mêmes fonctions SQL que le serveur MCP : aucun modèle n'est appelé ici.
Lancement local : uvicorn pokemon_rag.api.app:app --reload
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from pokemon_rag.config import DB_PATH
from pokemon_rag.structured.query_engine import get_pokemon_types

app = FastAPI(title="Pokémon RAG", version="0.1.0")


@app.exception_handler(FileNotFoundError)
def database_missing(request: Request, exc: FileNotFoundError) -> JSONResponse:
    """Base absente : service indisponible (503), pas une erreur interne ni un Pokémon inconnu."""
    detail = f"{exc}. Placer pokemon.db dans data/ (voir le README)."
    return JSONResponse(status_code=503, content={"detail": detail})


@app.get("/health")
def health() -> dict[str, str]:
    """Indique que le service répond et que la base est présente ; ne l'ouvre pas."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}")
    return {"status": "ok"}


@app.get("/pokemon/{name}/types")
def pokemon_types(name: str, form: str | None = None) -> dict[str, Any]:
    """Types d'un Pokémon nommé ; `form` est un paramètre de requête facultatif."""
    try:
        return get_pokemon_types(pokemon=name, form=form)
    except ValueError as exc:
        # Le moteur lève ValueError pour un nom ou une forme introuvable.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
