"""API HTTP au-dessus du moteur structuré.

Chaque route expose la fonction d'un outil MCP structuré : mêmes arguments,
mêmes validations, même SQL. Aucun modèle n'est appelé ; la recherche
documentaire, qui en charge, n'est pas exposée.
Lancement local : uvicorn pokemon_rag.api.app:app --reload
"""
import inspect
from functools import wraps
from typing import Annotated, Any, Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from pokemon_rag.config import DB_PATH
from pokemon_rag.mcp import server as tools

app = FastAPI(title="Pokémon RAG", version="0.1.0")

ROUTES = {
    "/pokemon": tools.pokemon_search,
    "/pokemon/{pokemon}/types": tools.pokemon_types,
    "/pokemon/{pokemon}/identity": tools.pokemon_pokedex_identity,
    "/pokemon/{pokemon}/evolutions": tools.pokemon_evolutions,
    "/pokemon/{pokemon}/signature-moves": tools.pokemon_signature_moves,
    "/pokemon/{pokemon}/moves": tools.pokemon_moves,
    "/pokemon/{pokemon}/level-up-moves": tools.pokemon_level_up_moves,
    "/pokemon/{pokemon}/machine-moves": tools.pokemon_machine_moves,
    "/pokemon/{pokemon}/moves/{move}/learning-methods": tools.pokemon_move_learning_methods,
}


@app.exception_handler(FileNotFoundError)
def database_missing(request: Request, exc: FileNotFoundError) -> JSONResponse:
    """Base absente : service indisponible (503), pas une erreur interne ni un Pokémon inconnu."""
    detail = f"{exc}. Placer pokemon.db dans data/ (voir le README)."
    return JSONResponse(status_code=503, content={"detail": detail})


@app.exception_handler(ValueError)
def engine_refusal(request: Request, exc: ValueError) -> JSONResponse:
    """Refus du moteur : 404 sur une route qui nomme un Pokémon, 400 sur la recherche par filtres."""
    # ponytail: le moteur lève ValueError pour un nom introuvable comme pour un filtre invalide ;
    # le code suit donc la route, pas la cause. Les distinguer demande des exceptions typées.
    status = 404 if "pokemon" in request.path_params else 400
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    """Indique que le service répond et que la base est présente ; ne l'ouvre pas."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}")
    return {"status": "ok"}


def _as_route(tool: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Signature de l'outil, où une liste est déclarée Query : sinon FastAPI l'attend dans le corps."""
    signature = inspect.signature(tool, eval_str=True)
    parameters = [
        param.replace(annotation=Annotated[param.annotation, Query()]) if "list[" in str(param.annotation) else param
        for param in signature.parameters.values()
    ]

    @wraps(tool)
    def route(**kwargs: Any) -> dict[str, Any]:
        return tool(**kwargs)

    route.__signature__ = signature.replace(parameters=parameters)
    return route


for _path, _tool in ROUTES.items():
    # Seul le premier paragraphe décrit l'opération ; la suite s'adresse au modèle.
    app.get(_path, name=_tool.__name__, description=inspect.getdoc(_tool).split("\n\n")[0])(_as_route(_tool))
