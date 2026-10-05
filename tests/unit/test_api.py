"""API HTTP : vraie application FastAPI, moteur SQL simulé à la frontière."""
import pytest
from fastapi.testclient import TestClient

from pokemon_rag.api import app as api

client = TestClient(api.app)


def test_health_answers_without_touching_the_engine(monkeypatch):
    monkeypatch.setattr(api, "get_pokemon_types", lambda **_: pytest.fail("moteur appelé"))
    response = client.get("/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_types_passes_name_and_optional_form_to_the_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "get_pokemon_types", lambda **kwargs: calls.append(kwargs) or {"rows": [{"type_1_fr": "Eau"}]})
    assert client.get("/pokemon/Motisma/types").json() == {"rows": [{"type_1_fr": "Eau"}]}
    assert client.get("/pokemon/Motisma/types", params={"form": "wash"}).status_code == 200
    # Un nom avec espace ou accent arrive décodé au moteur.
    client.get("/pokemon/Méga-Dracaufeu X/types")
    assert calls == [{"pokemon": "Motisma", "form": None}, {"pokemon": "Motisma", "form": "wash"},
                     {"pokemon": "Méga-Dracaufeu X", "form": None}]


def test_unknown_pokemon_is_a_404_with_the_engine_message(monkeypatch):
    def unknown(**_):
        raise ValueError("Entrée Pokédex introuvable")
    monkeypatch.setattr(api, "get_pokemon_types", unknown)
    response = client.get("/pokemon/Inconnu/types")
    assert response.status_code == 404
    assert response.json() == {"detail": "Entrée Pokédex introuvable"}
