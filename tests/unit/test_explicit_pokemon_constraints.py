"""Catalogue injecté : mentions exactes et invariants, sans données ou modèle."""
from types import SimpleNamespace

import pytest

from pokemon_rag.agent.tool_guard import before_tool_guard
from pokemon_rag.constraints.query_constraints import extract_named_pokemon, reconcile_search_args


CATALOGUE = [("gouroutan","Gouroutan",None), ("sinistrail","Sinistrail",None),
             ("electrode","Électrode",None), ("ho-oh","Ho-Oh",None),
             ("raichu","Raichu",None), ("raichu-d-alola","Raichu","raichu-alola")]


@pytest.mark.parametrize("name,canonical", [("GOUROUTAN","Gouroutan"), ("Électrode","Électrode"),
                                           ("Ho-Oh","Ho-Oh"), ("sinistrail","Sinistrail")])
def test_wrong_species_is_restored_from_explicit_question(monkeypatch,name,canonical):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: CATALOGUE)
    ctx = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text=f"Quels sont les types de {name} ?")]))
    args = {"pokemon":"Wrong species"}
    assert before_tool_guard(SimpleNamespace(name="pokemon_types"), args, ctx) is None
    assert args["pokemon"] == canonical


def test_form_alias_wins_over_contained_species_and_multiple_targets_are_blocked():
    assert extract_named_pokemon("Types de Raichu d'Alola", CATALOGUE) == {"pokemon":"Raichu", "form":"raichu-alola"}
    with pytest.raises(ValueError):
        extract_named_pokemon("Compare Gouroutan et Sinistrail", CATALOGUE)
    assert extract_named_pokemon("Des Pokémon Eau", CATALOGUE) is None
    assert extract_named_pokemon("Gouroutanus", CATALOGUE) is None


def test_named_identity_refuses_search_with_required_compatible_call(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: CATALOGUE)
    ctx = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text="Quel est le numéro national de Sinistrail ?")]))
    result = before_tool_guard(SimpleNamespace(name="pokemon_search"), {}, ctx)
    assert result["required_tool"] == "pokemon_pokedex_identity"
    assert result["required_arguments"]["pokemon"] == "Sinistrail"


@pytest.mark.parametrize("question,expected", [
    ("Les Pokémon fabuleux introduits en cinquième génération", {"mythical":True}),
    ("Quel Pokémon fabuleux est le plus rapide ?", {"mythical":True}),
    ("Liste des Pokémon légendaires de génération 4", {"legendary":True}),
    ("Pokémon à la fois légendaires et fabuleux", {"legendary":True,"mythical":True}),
])
def test_independent_classifications_remove_invented_opposite_filter(question,expected):
    actual = reconcile_search_args(question, {"mythical":False,"legendary":False,"generation":5})
    assert {key:value for key,value in actual.items() if key in {"legendary","mythical"}} == expected
    assert actual["generation"] == 5


@pytest.mark.parametrize("question", ["Des Pokémon Spectre", "Les Pokémon Eau",
                                     "Les légendaires de génération 4"])
def test_simple_list_never_keeps_best_only(question):
    actual = reconcile_search_args(question, {"best_only":True,"sort_by":"national_number"})
    assert actual["best_only"] is False


@pytest.mark.parametrize("question", ["Pokémon non légendaires", "Pokémon légendaires ou fabuleux"])
def test_ambiguous_classification_is_blocked(question):
    with pytest.raises(ValueError):
        reconcile_search_args(question,{})


def test_top_without_repeated_pokemon_noun_and_unrelated_negative_clause():
    result = reconcile_search_args("Les 5 plus rapides",{"best_only":True})
    assert result["limit"] == 5 and result["best_only"] is False
    result = reconcile_search_args("Quel Pokémon légendaire est le plus rapide sans tenir compte des talents ?",{})
    assert result["legendary"] is True and result["best_only"] is True


def test_explicit_all_versions_is_not_mistaken_for_unknown_single_game(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: CATALOGUE)
    ctx = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(
        text="Quelles CT Gouroutan peut-il apprendre dans toutes les versions ?")]))
    args = {"pokemon":"Gourgeist","version_group":"sun-moon"}
    assert before_tool_guard(SimpleNamespace(name="pokemon_machine_moves"),args,ctx) is None
    assert args == {"pokemon":"Gouroutan","all_versions":True}


def test_named_stat_lookup_can_use_a_number_but_cannot_substitute_another_species(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue",lambda:CATALOGUE)
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.get_pokedex_identity",
                        lambda **kwargs:{"rows":[{"national_number":765}]})
    ctx = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text="Quelle est la Vitesse de Gouroutan ?")]))
    args = {"pokedex_number":428,"sort_by":"speed"}
    assert before_tool_guard(SimpleNamespace(name="pokemon_search"),args,ctx) is None
    assert args["pokedex_number"] == 765 and "pokemon" not in args
