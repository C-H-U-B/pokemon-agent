"""Sélection réelle de versions pour les CT, sans parsing ni LLM."""

import pytest

from pokemon_rag.mcp.server import pokemon_machine_moves

pytestmark = pytest.mark.real_data


def test_noivern_defaults_to_latest_machine_data_only():
    result = pokemon_machine_moves("Bruyverne")
    assert result["version_group"] == "scarlet-violet"
    assert result["version_selection"] == "latest_available"
    assert result["count"] == len(result["moves"]) > 0
    assert {move["version_group"] for move in result["moves"]} == {"scarlet-violet"}


def test_explicit_older_version_is_preserved():
    result = pokemon_machine_moves("Gouroutan", version_group="sun-moon")
    assert result["version_group"] == "sun-moon"
    assert result["version_selection"] == "explicit"
    assert result["moves"]
    assert {move["version_group"] for move in result["moves"]} == {"sun-moon"}


def test_explicit_unavailable_version_does_not_fall_back():
    result = pokemon_machine_moves("Bruyverne", version_group="red-blue")
    assert result["version_group"] == "red-blue"
    assert result["count"] == 0
    assert result["moves"] == []
