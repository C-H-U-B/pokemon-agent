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
    # Le guard lit ce vocabulaire à chaque appel d'outil : vide ici, un test le remplace s'il en dépend.
    import pokemon_rag.structured.query_engine as query_engine
    monkeypatch.setattr(query_engine, "_vocabulary_words", lambda path, modified: frozenset())
    # Catalogue des noms vide quand il vise la vraie base ; une base de test (DB_PATH remplacé) est lue.
    # Sans cela, son cache rempli par un test real_data lancé avant masque l'accès à la base, qui
    # n'échoue alors que sur une machine sans base.
    read_names = query_engine._name_catalogue
    monkeypatch.setattr(query_engine, "_name_catalogue", lambda path, modified: (
        () if Path(path).resolve() == DB_PATH.resolve() else read_names(path, modified)))


@pytest.fixture(autouse=True)
def forbid_models_without_marker(request, monkeypatch):
    if request.node.get_closest_marker("models"):
        return
    import pokemon_rag.rag.retrieval as retrieval
    def forbidden(*args, **kwargs):
        pytest.fail("Chargement de modèles interdit sans marqueur models")
    monkeypatch.setattr(retrieval, "initialize_retrieval", forbidden)
