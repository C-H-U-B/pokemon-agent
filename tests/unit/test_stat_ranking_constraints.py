"""Motifs de classement : contraintes explicites, aucun SQL/MCP/modèle."""
import pytest

from pokemon_rag.constraints.query_constraints import (
    extract_stat_ranking_args, reconcile_stat_ranking_args,
)


@pytest.mark.parametrize("question,stat,order,best,limit", [
    ("la méga avec le moins de défense", "defense","asc",True,30),
    ("Quel Pokémon a le moins d'Attaque Spéciale ?", "special-attack","asc",True,30),
    ("Quel est le Pokémon le plus lent ?", "speed","asc",True,30),
    ("Quel est le Pokémon le plus rapide ?", "speed","desc",True,30),
    ("Quel Pokémon a la meilleure Défense Spéciale ?", "special-defense","desc",True,30),
    ("Quel Pokémon a le plus de PV ?", "hp","desc",True,30),
    ("Quel Pokémon Feu a le plus d'Attaque ?", "attack","desc",True,30),
    ("Quel Pokémon a le meilleur total de statistiques ?", "base-stat-total","desc",True,30),
    ("Quels sont les 10 Pokémon les plus rapides ?", "speed","desc",False,10),
    ("Top5 des Pokémon avec la meilleure Défense", "defense","desc",False,5),
    ("Quels Pokémon de 7G sont les plus rapides ?", "speed","desc",True,30),
    ("Quels sont les Pokémon Méga les plus lents ?", "speed","asc",True,30),
    ("Les Pokémon avec les PV les plus élevés", "hp","desc",True,30),
    ("Quel Pokémon a la Défense la plus basse ?", "defense","asc",True,30),
    ("Quels sont les Pokémon ayant les pires Défenses Spéciales ?", "special-defense","asc",True,30),
])
def test_explicit_statistic_direction_and_top_size(question, stat, order, best, limit):
    result = extract_stat_ranking_args(question)
    assert result["sort_by"] == stat and result["sort_order"] == order
    assert result["best_only"] == best and result["limit"] == limit


@pytest.mark.parametrize("label,stat", [
    ("PV","hp"), ("Attaque","attack"), ("Défense","defense"),
    ("Attaque Spéciale","special-attack"), ("Défense Spéciale","special-defense"),
    ("Vitesse","speed"), ("total des statistiques de base","base-stat-total"),
])
@pytest.mark.parametrize("count", [None, 5, 10])
@pytest.mark.parametrize("cue,order", [("plus de","desc"), ("moins de","asc")])
def test_superlative_plural_vs_explicit_quantity_across_all_stats(label,stat,count,cue,order):
    quantity = "" if count is None else f"{count} "
    question = f"Quels sont les {quantity}Pokémon Méga de génération 4 avec le {cue} {label} ?"
    corrected = reconcile_stat_ranking_args(question, {
        "generation":4, "legendary":True, "mythical":False,
        "sort_by":"national_number", "best_only":count is not None, "limit":99})
    assert corrected["sort_by"] == stat and corrected["sort_order"] == order
    assert corrected["best_only"] == (count is None)
    assert corrected["limit"] == (30 if count is None else count)
    assert corrected["form_category"] == "mega"
    assert corrected["generation"] == 4 and corrected["legendary"] and not corrected["mythical"]


def test_missing_ranking_and_invented_steel_are_corrected_without_mutating_input():
    args = {"types":["Steel"],"form_category":"mega"}
    corrected = reconcile_stat_ranking_args("la méga avec le moins de défense", args)
    assert corrected == {"form_category":"mega", "sort_by":"defense", "sort_order":"asc",
                         "best_only":True,"limit":30,"offset":0}
    assert args == {"types":["Steel"],"form_category":"mega"}


def test_actual_type_and_other_tool_constraints_are_preserved():
    corrected = reconcile_stat_ranking_args("Quel Pokémon Eau/Vol a le meilleur total de statistiques ?",
        {"types":["Steel"],"generation":4,"legendary":True,"version_group":"latest"})
    assert corrected["types"] == ["water","flying"] and corrected["type_match"] == "all"
    assert corrected["generation"] == 4 and corrected["legendary"] is True
    assert corrected["version_group"] == "latest"


def test_move_type_not_confused_with_pokemon_type_in_ranking():
    corrected = reconcile_stat_ranking_args(
        "Quel Pokémon Feu pouvant apprendre une attaque Eau spéciale est le plus rapide ?",
        {"types":["water"],"move_type":"water","damage_class":"special"})
    assert corrected["types"] == ["fire"]
    assert corrected["move_type"] == "water" and corrected["damage_class"] == "special"


def test_all_megas_do_not_accidentally_exclude_x_y_variants():
    corrected = reconcile_stat_ranking_args("Quel Pokémon Méga a la meilleure Défense ?", {"form":"mega"})
    assert corrected["form_category"] == "mega" and "form" not in corrected


def test_specific_mega_variant_and_monotype_constraint_are_kept():
    result = reconcile_stat_ranking_args("Quel Pokémon Méga-X a le moins de Défense ?", {"form":"mega"})
    assert result["form"] == "mega-x" and result["form_category"] == "mega"
    result = reconcile_stat_ranking_args("Quel Pokémon uniquement de type Eau est le plus rapide ?", {})
    assert result["types"] == ["water"] and result["type_match"] == "exact"


def test_explicit_steel_kept_and_global_ranking_drops_invented_mega_category():
    assert reconcile_stat_ranking_args("Quel Pokémon Acier est le plus rapide ?", {})["types"] == ["steel"]
    assert "form_category" not in reconcile_stat_ranking_args(
        "Quels sont les 10 Pokémon les plus rapides ?", {"form_category":"mega"})


@pytest.mark.parametrize("question", ["Quels sont les types de Pikachu ?",
    "Qui est le plus rapide entre Pikachu et Raichu ?", "Quel Pokémon est le plus rapide entre Pikachu et Raichu ?",
    "Donne les 10 Pokémon les plus rapides à la page 2"])
def test_unrecognized_queries_and_named_comparisons_left_unchanged(question):
    args = {"types":["Steel"]}
    assert extract_stat_ranking_args(question) is None
    assert reconcile_stat_ranking_args(question,args) == args


@pytest.mark.parametrize("question", [
    "Quels sont les 0 Pokémon les plus rapides ?", "Quels sont les 101 Pokémon les plus rapides ?",
    "Quels sont les 5 Pokémon les plus rapides et les 10 Pokémon les plus lents ?",
    "Quel Pokémon a le plus d'Attaque et le moins de Défense ?",
    "Quel Pokémon de type Inconnu est le plus rapide ?",
])
def test_ambiguous_or_invalid_recognized_requests_are_rejected(question):
    with pytest.raises(ValueError):
        reconcile_stat_ranking_args(question,{})


from pokemon_rag.constraints.query_constraints import (  # noqa: E402
    SUBGROUP_ALIASES, extract_classifications, extract_explicit_constraints, extract_subgroup,
)


@pytest.mark.parametrize("question, subgroup", [
    ("Quel est le fossile le plus rapide ?", "Fossile"),
    ("Quels sont les starters de la première génération ?", "Starter"),
    ("Liste les pseudo-légendaires", "Pseudo-légendaire"),
    ("Quel Pokémon bébé a le plus de PV ?", "Pokémon bébé"),
    ("Quelles sont les Ultra-Chimères ?", "Ultra-Chimère"),
    ("Quel paradoxe antique est le plus rapide ?", "Paradoxe antique"),
    ("Quels sont les légendaires secondaires de Sinnoh ?", "Légendaire secondaire"),
    ("Quels sont les Pokémon légendaires ?", None),            # classification, pas sous-groupe
    ("Quels sont les types de Fossilis ?", None),              # jamais par sous-chaîne
    ("Quelles capacités apprend Dracolosse ?", None),
])
def test_subgroup_is_recognised_only_from_its_literal_name(question, subgroup):
    assert extract_subgroup(question) == subgroup
    assert extract_explicit_constraints(question).subgroup == subgroup


def test_two_named_subgroups_are_not_representable():
    with pytest.raises(ValueError, match="sous-groupes"):
        extract_subgroup("Quels fossiles sont aussi des starters ?")


def test_pseudo_legendary_is_not_a_legendary_mention():
    # Régression : le filtre légendaire, ajouté à tort, vidait la liste des pseudo-légendaires.
    assert extract_classifications("Quels sont les pseudo-légendaires ?") == {}
    assert extract_classifications("Quels sont les légendaires ?") == {"legendary": True}
    assert extract_classifications("Quel légendaire secondaire est le plus rapide ?") == {"legendary": True}


@pytest.mark.parametrize("question, expected", [
    ("Quel est le fossile le plus rapide ?", {"sort_by": "speed", "sort_order": "desc", "best_only": True}),
    ("Quel starter a le plus d'Attaque ?", {"sort_by": "attack", "sort_order": "desc", "best_only": True}),
    ("Quels sont les 3 fossiles les plus lents ?", {"sort_by": "speed", "sort_order": "asc", "best_only": False, "limit": 3}),
    ("Quel est le légendaire le plus rapide ?", {"sort_by": "speed", "sort_order": "desc", "best_only": True}),
    ("Quels sont les 5 pseudo-légendaires avec le plus de PV ?", {"sort_by": "hp", "sort_order": "desc", "limit": 5}),
])
def test_ranking_over_a_named_group_needs_no_pokemon_word(question, expected):
    # Régression : sans le mot « Pokémon », le superlatif était « non reconnu » et l'appel refusé.
    ranking = extract_stat_ranking_args(question)
    assert ranking is not None and expected.items() <= ranking.items()


def test_superlative_about_something_else_is_still_not_a_pokemon_ranking():
    assert extract_stat_ranking_args("Quelle est la capacité la plus puissante de Dracolosse ?") is None


@pytest.mark.real_data
def test_every_subgroup_alias_names_a_value_of_the_spreadsheet():
    import sqlite3
    from pokemon_rag.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        cells = [row[0] for row in conn.execute("SELECT DISTINCT sous_groupe FROM custom_pokedex_fr WHERE sous_groupe IS NOT NULL")]
    known = {part.strip() for cell in cells for part in cell.split(" ; ")}
    assert set(SUBGROUP_ALIASES.values()) <= known
