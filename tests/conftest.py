"""Les tests légers échouent s'ils tentent d'ouvrir les données de production."""
from pathlib import Path
import sqlite3

import pytest


@pytest.fixture(autouse=True)
def forbid_project_database_in_light_tests(request, monkeypatch):
    if request.node.get_closest_marker("real_data"):
        return
    from pokemon_rag.config import DB_PATH, POKEAPI_DB_PATH
    original = sqlite3.connect
    def connect(database, *args, **kwargs):
        if str(database) != ":memory:":
            path = str(database).removeprefix("file:").split("?", 1)[0]
            if Path(path).resolve() in {DB_PATH.resolve(), POKEAPI_DB_PATH.resolve()}:
                pytest.fail("Test léger : accès interdit aux bases du projet")
        return original(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)


@pytest.fixture(autouse=True)
def forbid_models_without_marker(request, monkeypatch):
    if request.node.get_closest_marker("models"):
        return
    import pokemon_rag.rag.retrieval as retrieval
    def forbidden(*args, **kwargs):
        pytest.fail("Chargement de modèles interdit sans marqueur models")
    monkeypatch.setattr(retrieval, "initialize_retrieval", forbidden)
