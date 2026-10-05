"""Régressions sur la vraie base, sans parsing de question ni appel modèle."""

import pytest

from pokemon_rag.mcp.server import pokemon_types
from pokemon_rag.structured.query_engine import get_level_up_moves, get_pokedex_identity

pytestmark = pytest.mark.real_data


@pytest.mark.parametrize("name, types", [
    ("Nigirigon", ("Dragon", "Eau")),
    ("Tatsugiri", ("Dragon", "Eau")),
    ("Giratina", ("Spectre", "Dragon")),
    ("Shaymin", ("Plante", None)),
    ("Xerneas", ("Fée", None)),
    ("Arceus", ("Normal", None)),
    ("Silvallié", ("Normal", None)),
    ("Ceriflor", ("Plante", None)),
    ("Mimiqui", ("Spectre", "Fée")),
    ("Morpeko", ("Électrik", "Ténèbres")),
])
def test_species_name_resolves_default_custom_form(name, types):
    result = pokemon_types(name)
    row = result["rows"][0]
    assert (row["type_1_fr"], row["type_2_fr"]) == types
    assert result["count"] == 1


@pytest.mark.parametrize("species, battle_form, number", [
    ("Xerneas", "Xerneas Déchaîné", 716),
    ("Mimiqui", "Mimiqui Forme Démasquée", 778),
    ("Morpeko", "Morpeko Affamé", 877),
])
def test_species_name_is_not_its_battle_form(species, battle_form, number):
    # L'espèce seule désigne la forme par défaut ; la forme de combat reste nommable.
    default = get_pokedex_identity(species)
    assert default["rows"][0]["national_number"] == number
    assert default["pokemon"] != battle_form
    assert pokemon_types(battle_form)["pokemon"] == battle_form


@pytest.mark.parametrize("asked, shown, form", [
    ("Xerneas", "Xerneas", "Mode Paisible"),
    ("Zygarde", "Zygarde", "Forme 50 %"),
    ("Arceus", "Arceus", "Type : Normal"),
    ("Tatsugiri", "Nigirigon", "Forme Courbée"),  # nom anglais → nom français de l'espèce
    ("Pikachu", "Pikachu", None),
    ("Xerneas Paisible", "Xerneas Paisible", "Mode Paisible"),
    ("Zygarde Forme 10 %", "Zygarde Forme 10 %", "Forme 10 %"),
])
def test_species_asked_without_form_is_named_as_the_species(asked, shown, form):
    # Régression : « Xerneas » répondait « Xerneas Paisible », « Zygarde » « Zygarde Forme 50 % ».
    for function in (pokemon_types, get_pokedex_identity):
        result = function(asked)
        assert (result["pokemon"], result["rows"][0]["name_fr"], result["form"]) == (shown, shown, form)


def test_full_form_name_and_identity_are_preserved():
    result = pokemon_types("Nigirigon Forme Courbée")
    assert result["pokemon"] == "Nigirigon Forme Courbée"
    assert get_pokedex_identity("Nigirigon")["rows"][0]["national_number"] == 978


@pytest.mark.parametrize("pokemon, form", [
    ("Nigirigon", "forme inexistante"),
    ("Espèce inexistante", None),
])
def test_missing_species_or_requested_form_remains_an_error(pokemon, form):
    with pytest.raises(ValueError):
        pokemon_types(pokemon, form)


def test_moves_retain_french_names_and_technical_identifiers():
    # Sans jeu, seul le dernier jeu est renvoyé : l'historique multijeux se demande explicitement.
    result = get_level_up_moves("Opermine", min_level=10, max_level=25, all_versions=True)
    names = {move["identifier"]: move["name_fr"] for move in result["moves"]}
    assert names["fury-swipes"] == "Combo-Griffe"
    assert names["slash"] == "Tranche"
    assert names["clamp"] == "Claquoir"
    assert names["rock-polish"] == "Poliroche"
    assert all(10 <= move["level"] <= 25 for move in result["moves"])
    assert "omega-ruby-alpha-sapphire" in {
        move["version_group"] for move in result["moves"]
    }
