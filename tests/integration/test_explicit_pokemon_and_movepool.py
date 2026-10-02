"""Catalogue et movepools SQLite réels, sans parseur ni LLM."""
import pytest

from pokemon_rag.constraints.query_constraints import extract_named_pokemon
from pokemon_rag.structured.query_engine import (
    pokemon_name_catalogue, get_level_up_moves, get_move_learning_methods, get_machine_moves,
)

pytestmark = pytest.mark.real_data


@pytest.mark.parametrize("name", ["Gouroutan", "Sinistrail", "Électrode", "Ho-Oh", "Porygon-Z"])
def test_names_from_real_database(name):
    result = extract_named_pokemon(f"Question sur {name}", pokemon_name_catalogue())
    assert result == {"pokemon":name}


def test_french_form_name_is_preserved_from_real_catalogue():
    result = extract_named_pokemon("Types de Méga-Mewtwo X", pokemon_name_catalogue())
    assert result["pokemon"] == "Mewtwo" and result["form"] == "mewtwo-mega-x"


def test_latest_level_up_selected_before_level_filter_and_history_still_accessible():
    current = get_level_up_moves("Opermine", min_level=10,max_level=25)
    history = get_level_up_moves("Opermine",min_level=10,max_level=25,all_versions=True)
    assert current["version_selection"] == "latest_available"
    assert {row["version_group"] for row in current["moves"]} == {current["version_group"]}
    assert current["count"] == len(current["moves"]) < history["count"]
    old = get_level_up_moves("Opermine",version_group="x-y",min_level=10,max_level=25)
    assert {row["version_group"] for row in old["moves"]} == {"x-y"}
    assert {(row["move_id"],row["level"]) for row in current["moves"]} != {
        (row["move_id"],row["level"]) for row in old["moves"]}


def test_methods_default_to_latest_species_movepool_and_history_is_opt_in():
    current = get_move_learning_methods("Concombaffe","Toxik")
    history = get_move_learning_methods("Concombaffe","Toxik",all_versions=True)
    assert current["version_selection"] == "latest_available"
    assert {row["version_group"] for row in current["methods"]} <= {current["version_group"]}
    assert len({row["version_group"] for row in history["methods"]}) > 1
    machines = get_machine_moves("Gouroutan",all_versions=True)
    assert machines["version_selection"] == "all_versions"
    assert len({row["version_group"] for row in machines["moves"]}) > 1


def test_single_version_cannot_be_silently_combined_with_all_history():
    with pytest.raises(ValueError):
        get_level_up_moves("Opermine",version_group="x-y",all_versions=True)
    with pytest.raises(ValueError):
        get_machine_moves("Gouroutan",all_versions="yes")
