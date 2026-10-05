"""API HTTP : vraie application FastAPI et vraies fonctions d'outils, moteur SQL simulé à la frontière."""
import pytest
from fastapi.testclient import TestClient

from pokemon_rag.api import app as api
from pokemon_rag.mcp import server as tools

client = TestClient(api.app)

ENGINE = ["search_pokemon", "get_pokemon_types", "get_pokedex_identity", "get_evolutions", "get_signature_moves",
          "get_pokemon_moves", "get_level_up_moves", "get_machine_moves", "get_move_learning_methods"]


@pytest.fixture
def engine(monkeypatch):
    """Remplace les neuf fonctions du moteur ; renvoie les appels reçus, par nom."""
    calls = []
    for name in ENGINE:
        monkeypatch.setattr(tools, name, lambda _name=name, **kwargs: calls.append((_name, kwargs)) or {"operation": _name})
    return calls


def test_health_answers_without_touching_the_engine(monkeypatch, tmp_path, engine):
    database = tmp_path / "pokemon.db"
    database.touch()
    monkeypatch.setattr(api, "DB_PATH", database)
    response = client.get("/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert engine == []


def test_health_is_unavailable_when_the_database_file_is_missing(monkeypatch, tmp_path):
    # Régression : le service se disait sain alors que toutes les routes de données échouaient.
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "pokemon.db")
    response = client.get("/health")
    assert response.status_code == 503
    assert "Base introuvable" in response.json()["detail"]
    assert "README" in response.json()["detail"]


@pytest.mark.parametrize("url, params, function, expected", [
    ("/pokemon", {"generation": 6, "legendary": "true", "types": ["Feu", "Vol"], "type_match": "exact",
                  "sort_by": "speed", "sort_order": "desc", "best_only": "true", "limit": 5},
     "search_pokemon", {"generation": 6, "legendary": True, "mythical": None, "types": ["Feu", "Vol"],
                        "type_match": "exact", "sort_by": "speed", "sort_order": "desc", "best_only": True,
                        "limit": 5, "offset": 0}),
    ("/pokemon", {}, "search_pokemon", {"types": None, "sort_by": "national_number", "limit": 30}),
    ("/pokemon/Motisma/types", {"form": "wash"}, "get_pokemon_types", {"pokemon": "Motisma", "form": "wash"}),
    # Un nom avec espace ou accent arrive décodé au moteur.
    ("/pokemon/Méga-Dracaufeu X/identity", {}, "get_pokedex_identity", {"pokemon": "Méga-Dracaufeu X", "form": None}),
    ("/pokemon/Évoli/evolutions", {"version_group": "sword-shield"}, "get_evolutions",
     {"pokemon": "Évoli", "form": None, "version_group": "sword-shield"}),
    ("/pokemon/Pikachu/signature-moves", {}, "get_signature_moves", {"pokemon": "Pikachu", "form": None}),
    ("/pokemon/Pikachu/moves", {"move_type": "Électrik", "damage_class": "special", "min_power": 80, "limit": 0},
     "get_pokemon_moves", {"pokemon": "Pikachu", "move_type": "Électrik", "damage_class": "special",
                           "min_power": 80, "max_power": None, "limit": 0}),
    ("/pokemon/Pikachu/level-up-moves", {"min_level": 10, "max_level": 20}, "get_level_up_moves",
     {"pokemon": "Pikachu", "min_level": 10, "max_level": 20, "all_versions": False}),
    ("/pokemon/Pikachu/machine-moves", {"all_versions": "true"}, "get_machine_moves",
     {"pokemon": "Pikachu", "version_group": None, "all_versions": True}),
    ("/pokemon/Pikachu/moves/Fatal-Foudre/learning-methods", {"version_group": "red-blue"}, "get_move_learning_methods",
     {"pokemon": "Pikachu", "move": "Fatal-Foudre", "version_group": "red-blue"}),
])
def test_each_route_passes_typed_arguments_to_its_engine_function(engine, url, params, function, expected):
    response = client.get(url, params=params)
    assert (response.status_code, response.json()) == (200, {"operation": function})
    (called, kwargs), = engine
    assert called == function
    assert expected.items() <= kwargs.items()


def test_routes_cover_the_structured_tools_and_not_document_search():
    names = {route.name for route in api.app.routes if route.path.startswith("/pokemon")}
    assert names == {"pokemon_search", "pokemon_types", "pokemon_pokedex_identity", "pokemon_evolutions",
                     "pokemon_signature_moves", "pokemon_moves", "pokemon_level_up_moves",
                     "pokemon_machine_moves", "pokemon_move_learning_methods"}
    # Aucune route n'attend de corps : tous les arguments viennent de l'URL.
    assert not any(route.body_field for route in api.app.routes if route.path.startswith("/pokemon"))


@pytest.mark.parametrize("url, function, status", [
    ("/pokemon/Inconnu/types", "get_pokemon_types", 404),
    ("/pokemon/Inconnu/moves", "get_pokemon_moves", 404),
    ("/pokemon/Pikachu/moves/Inconnue/learning-methods", "get_move_learning_methods", 404),
    ("/pokemon", "search_pokemon", 400),
])
def test_engine_refusal_keeps_its_message_and_is_never_a_500(monkeypatch, url, function, status):
    def refuse(**_):
        raise ValueError("Refus du moteur")
    monkeypatch.setattr(tools, function, refuse)
    response = TestClient(api.app, raise_server_exceptions=False).get(url)
    assert (response.status_code, response.json()) == (status, {"detail": "Refus du moteur"})


@pytest.mark.parametrize("url, params", [
    ("/pokemon", {"sort_by": "vitesse"}),
    ("/pokemon", {"type_match": "some"}),
    ("/pokemon", {"generation": "six"}),
    ("/pokemon/Pikachu/level-up-moves", {"min_level": "dix"}),
])
def test_value_outside_the_schema_is_rejected_before_the_engine(engine, url, params):
    assert client.get(url, params=params).status_code == 422
    assert engine == []


def test_missing_database_on_a_data_route_is_503_not_500_or_404(monkeypatch):
    def missing(**_):
        raise FileNotFoundError("Base introuvable : /app/data/pokemon.db")
    monkeypatch.setattr(tools, "get_pokemon_types", missing)
    response = TestClient(api.app, raise_server_exceptions=False).get("/pokemon/Pikachu/types")
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Base introuvable : /app/data/pokemon.db")
