"""Invariants avant outil : extracteurs réels, catalogue et contexte injectés.

Risque : une contrainte utilisateur oubliée/contredite atteint l'outil, ou un
nombre/adjectif hors contexte devient un filtre. Aucun serveur, base ou LLM.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pokemon_rag.agent.tool_guard import before_tool_guard
from pokemon_rag.constraints.query_constraints import (
    extract_explicit_constraints, extract_generation, extract_move_constraints,
    extract_national_pokedex_number, extract_pokemon_types, extract_power_bounds,
)


CATALOGUE = [("porygon-z", "Porygon-Z", None), ("munja", "Munja", None),
             ("flabebe", "Flabébé", None), ("krakos", "Krakos", None),
             ("motisma", "Motisma", None), ("motisma-lavage", "Motisma", "rotom-wash"),
             ("nigirigon", "Nigirigon", None), ("gouroutan", "Gouroutan", None)]


@pytest.fixture(autouse=True)
def catalogue(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: CATALOGUE)


def guard(question, name, args):
    ctx = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text=question)]))
    return before_tool_guard(SimpleNamespace(name=name), args, ctx)


@pytest.mark.parametrize("proposal", [{}, {"damage_class":"special","move_type":"water","min_power":80},
                                    {"damage_class":"physical","move_type":"fire","min_power":120,"max_power":130}])
def test_explicit_move_filters_are_authoritative_and_idempotent(proposal):
    question = "Quelles capacités SPÉCIALES de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre ?"
    args = {"pokemon":"Gourgeist", **proposal}
    assert guard(question,"pokemon_moves",args) is None
    assert args == {"pokemon":"Nigirigon","damage_class":"special","move_type":"water",
                    "min_power":80,"max_power":None}
    repaired = deepcopy(args)
    assert guard(question,"pokemon_moves",args) is None
    assert args == repaired


@pytest.mark.parametrize("name", ["pokemon_machine_moves","pokemon_level_up_moves","pokemon_types","pokemon_rag_search"])
def test_incompatible_tools_cannot_silently_drop_move_constraints_or_mutate_proposal(name):
    args = {"pokemon":"Wrong species"}
    original = deepcopy(args)
    result = guard("Quelles capacités physiques Krakos peut-il apprendre ?",name,args)
    assert result["error"] == "unsupported_move_constraints"
    assert result["required_arguments"]["damage_class"] == "physical"
    assert args == original


@pytest.mark.parametrize("question,expected", [
    ("Quelles attaques physiques Munja apprend-il ?", {"damage_class":"physical"}),
    ("Quelles capacités de statut Flabébé peut-il apprendre ?", {"damage_class":"status"}),
    ("Quelles capacités de catégorie spéciale Motisma apprend-il ?", {"damage_class":"special"}),
    ("Quel Pokémon peut apprendre une attaque Eau spéciale ?", {"move_type":"water","damage_class":"special"}),
    ("Quel Pokémon a la meilleure Attaque Spéciale ?", {}),
    ("Quels Pokémon ont les meilleures Attaques Spéciales ?", {}),
    ("Quelle est la Défense Spéciale de Munja ?", {}),
    ("Décris l'apparence physique de Munja", {}),
    ("Des capacités de puissance inconnue", {}),
])
def test_damage_class_is_attached_to_moves_and_never_inferred_from_power_or_statistics(question,expected):
    assert extract_move_constraints(question) == expected


@pytest.mark.parametrize("question", ["Des capacités physiques ou spéciales", "Des attaques Eau et Feu",
                                     "Des capacités spéciales et physiques", "Sans les capacités physiques",
                                     "Des capacités spéciales de type Eau ou Glace"])
def test_move_disjunctions_and_negations_are_blocked(question):
    args = {"pokemon":"Munja"}
    result = guard(question,"pokemon_moves",args)
    assert result["error"] == "invalid_explicit_constraints"
    assert args == {"pokemon":"Munja"}


@pytest.mark.parametrize("question,expected", [
    ("Des capacités d'au moins 100 de puissance", (100,None)),
    ("Des capacités d'au plus 95 de puissance", (None,95)),
    ("Des capacités de plus de 80 de puissance", (81,None)),
    ("Des capacités de moins de 80 de puissance", (None,79)),
    ("Des capacités de puissance entre 70 et 100", (70,100)),
    ("Des capacités entre 70 et 100 de puissance", (70,100)),
    ("Des capacités de puissance 90", (90,90)),
    ("Des capacités de puissance 90 minimum", (90,None)),
    ("Des capacités de puissance 90 maximum", (None,90)),
    ("Top 5 Pokémon de génération 7 au niveau 40", None),
])
def test_power_uses_only_explicit_numeric_power_relationship(question,expected):
    assert extract_power_bounds(question) == expected


@pytest.mark.parametrize("question", ["Des capacités de puissance entre 100 et 80",
                                     "Des capacités de puissance 80 ou 100",
                                     "Des capacités d'environ 100 de puissance",
                                     "Des capacités de puissance >= 80",
                                     "Des capacités d'au moins -100 de puissance",
                                     "Des capacités de puissance 80,5"])
def test_ambiguous_or_impossible_power_never_becomes_an_exact_filter(question):
    args = {"pokemon":"Munja","min_power":80}
    assert guard(question,"pokemon_moves",args)["error"] == "invalid_explicit_constraints"
    assert args == {"pokemon":"Munja","min_power":80}


def test_all_numeric_domains_and_move_filters_survive_together():
    question = ("Quels Pokémon numéro 369 du Pokédex national de génération 3 apprennent "
                "des capacités physiques de type Eau d'au moins 80 de puissance "
                "entre les niveaux 20 et 40 dans Pokémon Soleil ?")
    args = {"pokedex_number":25,"generation":7,"damage_class":"special","min_power":150,
            "min_level":2,"max_level":90,"version_group":"sword-shield"}
    assert guard(question,"pokemon_search",args) is None
    assert args == {"pokedex_number":369,"generation":3,"damage_class":"physical","move_type":"water",
                    "min_power":80,"max_power":None,"min_level":20,"max_level":40,
                    "learning_method":"level-up","version_group":"sun-moon"}


@pytest.mark.parametrize("number", [25, 213, 352, 618, 1000])
def test_national_number_blocks_guessed_identity_then_allows_explicit_retry(number):
    question = f"Quel Pokémon porte le numéro {number} du Pokédex national ?"
    args = {"pokemon":"Gigalith"}
    rejected = guard(question,"pokemon_pokedex_identity",args)
    assert rejected["error"] == "unsupported_pokedex_number_constraint"
    assert rejected["required_tool"] == "pokemon_search"
    retry = rejected["required_arguments"]
    assert retry == {"pokedex_number":number}
    assert guard(question,"pokemon_search",retry) is None
    assert args == {"pokemon":"Gigalith"}


@pytest.mark.parametrize("question,number", [
    ("Pokédex national 213", 213),
    ("Pokémon numéro 213 de génération 2 au niveau 30", 213),
    ("Pokémon n° 352 avec les 5 capacités les plus puissantes", 352),
    ("Pokémon de génération 7 au niveau 30", None),
])
def test_multiple_numbers_are_scoped_by_their_labels(question,number):
    assert extract_national_pokedex_number(question) == number


@pytest.mark.parametrize("question", ["Pokémon numéros 213 et 352", "Pokémon numéro 25 du Pokédex de Kanto",
                                     "Pokémon numéro 25,5"])
def test_multiple_or_regional_pokedex_numbers_are_not_national(question):
    assert guard(question,"pokemon_search",{})["error"] == "invalid_explicit_constraints"


@pytest.mark.parametrize("question,generation", [
    ("Pokémon introduits en QUATRIÈME génération", 4), ("Pokémon de 7G", 7),
    ("Pokémon de 3e génération", 3), ("Pokémon de génération 9", 9),
    ("Pokémon de première génération", 1), ("Pokémon dans Épée", None),
])
def test_generation_is_explicit_origin_not_inferred_from_game(question,generation):
    assert extract_generation(question) == generation


@pytest.mark.parametrize("question", ["Pokémon de génération 4 ou 5", "Pokémon de générations 4 et 5",
                                     "Pokémon après la quatrième génération", "Pokémon de génération 3,5"])
def test_generation_alternatives_and_ranges_are_not_single_filters(question):
    assert guard(question,"pokemon_search",{})["error"] == "invalid_explicit_constraints"


@pytest.mark.parametrize("question,expected", [
    ("Des Pokémon de type Eau et Vol", {"types":("water","flying"),"type_match":"all"}),
    ("Des Pokémon de type Feu ou Glace", {"types":("fire","ice"),"type_match":"any"}),
    ("Des Pokémon uniquement de type Électrik", {"types":("electric",),"type_match":"exact"}),
    ("Quel Pokémon de type Glace pur est le plus rapide ?", {"types":("ice",),"type_match":"exact"}),
    ("Des Pokémon Feu purs", {"types":("fire",),"type_match":"exact"}),
    ("Des Pokémon Eau/Vol", {"types":("water","flying"),"type_match":"all"}),
    ("Quel Pokémon Feu apprend une attaque Eau spéciale ?", {"types":("fire",),"type_match":"all"}),
    ("Quelles capacités de type Eau Krakos apprend-il ?", {}),
    ("Quels sont les types de Flabébé ?", {}), ("Pokémon résistants au Feu", {}),
    ("Les Pokémon combattent au sol", {}),
])
def test_species_type_and_move_type_have_separate_literal_contexts(question,expected):
    assert extract_pokemon_types(question) == expected


@pytest.mark.parametrize("question,expected", [
    # Régression : « attaque » au singulier valait la statistique, et le type disparaissait sans refus.
    ("Quelle est l'attaque de type Dragon de Dracolosse ?", "dragon"),
    ("Quelle attaque de type Dragon Dracolosse apprend-il ?", "dragon"),
    ("Quel Pokémon a la meilleure attaque de type Dragon ?", None),   # superlatif : classement sur la statistique
    ("Quel Pokémon de type Dragon a la meilleure Attaque ?", None),
])
def test_singular_attack_followed_by_a_type_names_a_move_not_the_stat(question, expected):
    assert extract_explicit_constraints(question).move_type == expected


def test_unrelated_or_does_not_turn_double_type_into_union():
    args = {"types":["fire"],"type_match":"any"}
    assert guard("Les Pokémon Eau/Vol les plus rapides, sans objets ou talents", "pokemon_search", args) is None
    assert args["types"] == ["water","flying"] and args["type_match"] == "all"


def test_generation_classifications_and_types_override_wrong_values_together():
    args = {"generation":1,"legendary":True,"mythical":False,"types":["fire"],"type_match":"any"}
    assert guard("Quels Pokémon mythiques de troisième génération sont de type Acier et Psy ?", "pokemon_search", args) is None
    assert args == {"generation":3,"mythical":True,"types":["steel","psychic"],"type_match":"all"}
    assert guard("Les Pokémon légendaires de génération 4", "pokemon_types", {})["error"] == "unsupported_search_constraints"


def test_full_form_alias_survives_wrong_species_and_form():
    args = {"pokemon":"Wrong species","form":"heat"}
    assert guard("Quels sont les types de MOTISMA LAVAGE ?", "pokemon_types", args) is None
    assert args == {"pokemon":"Motisma","form":"rotom-wash"}


def test_ambiguous_names_forms_and_regions_are_blocked_atomically():
    for question in ("Types de Munja et Flabébé", "Types des formes d'Alola et de Galar de Motisma"):
        args = {"pokemon":"Wrong species","form":"wrong"}
        assert guard(question,"pokemon_types",args) is not None
        assert args == {"pokemon":"Wrong species","form":"wrong"}


def test_no_named_species_means_no_name_invention_and_no_unrequested_numeric_filters():
    args = {"pokemon":"Chosen by model"}
    assert guard("Quelles capacités sont apprises par niveau en génération 4 ?", "pokemon_search", {}) is None
    assert guard("Des capacités spéciales", "pokemon_moves", args) is None
    assert args == {"pokemon":"Chosen by model","damage_class":"special"}


def test_number_and_named_target_contradiction_is_blocked(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.get_pokedex_identity",lambda **kwargs:{"rows":[{"national_number":292}]})
    args = {"pokedex_number":352}
    result = guard("Pokémon numéro 352 du Pokédex national : Munja", "pokemon_search", args)
    assert result["error"] == "invalid_explicit_constraints" and args == {"pokedex_number":352}


def test_level_range_intersects_later_bound_and_does_not_ignore_alternatives():
    args = {"pokemon":"Munja","min_level":1,"max_level":99}
    assert guard("Capacités Munja entre les niveaux 10 et 30 et avant le niveau 20", "pokemon_level_up_moves", args) is None
    assert (args["min_level"],args["max_level"]) == (10,19)
    assert guard("Capacités entre les niveaux 10 et 30 ou au niveau 50", "pokemon_level_up_moves", {})["error"] == "ambiguous_level_constraints"
    args = {"pokemon":"Munja","min_level":90,"max_level":99}
    assert guard("Capacités Munja jusqu'au niveau 30", "pokemon_level_up_moves", args) is None
    assert args["min_level"] is None and args["max_level"] == 30
    assert guard("Capacités après le niveau 20 mais avant 40", "pokemon_level_up_moves", {})["error"] == "ambiguous_level_constraints"


@pytest.mark.parametrize("wording,bounds", [("au niveau 20 minimum",(20,None)),
                                           ("au niveau 30 maximum",(None,30)),
                                           ("au moins le niveau 20",(20,None))])
def test_explicit_inequality_cannot_be_truncated_into_exact_level(wording,bounds):
    args = {"pokemon":"Munja"}
    assert guard(f"Capacités Munja {wording}","pokemon_level_up_moves",args) is None
    assert (args["min_level"],args["max_level"]) == bounds


@pytest.mark.parametrize("title,identifier", [
    ("Ultra-Soleil", "ultra-sun-ultra-moon"), ("Rouge Feu", "firered-leafgreen"),
    ("Diamant Étincelant", "brilliant-diamond-shining-pearl"),
    ("Rubis Oméga", "omega-ruby-alpha-sapphire"), ("sword-shield", "sword-shield"),
])
def test_complete_game_title_wins_over_contained_short_alias(title,identifier):
    args = {"pokemon":"Porygon-Z","version_group":"red-blue"}
    assert guard(f"Quelles CT Porygon-Z apprend-il dans Pokémon {title} ?", "pokemon_machine_moves", args) is None
    assert args["version_group"] == identifier


@pytest.mark.parametrize("stat", ["PV", "Attaque", "Défense", "Attaque Spéciale", "Défense Spéciale", "Vitesse", "total des statistiques"])
def test_incompatible_tool_cannot_execute_recognized_ranking(stat):
    result = guard(f"Quels sont les 5 Pokémon avec le plus de {stat} ?", "pokemon_types", {})
    assert result["error"] == "unsupported_search_constraints"
    assert result["required_arguments"]["best_only"] is False
    assert result["required_arguments"]["limit"] == 5


def test_ambiguous_ranking_keeps_proposal_unchanged():
    args = {"types":["steel"],"best_only":True}
    assert guard("Quel Pokémon a le plus d'Attaque et le moins de Défense ?", "pokemon_search", args)["error"] == "invalid_explicit_constraints"
    assert args == {"types":["steel"],"best_only":True}


def test_numeric_minimum_is_not_misread_as_an_optimum_and_top_survives_level_range():
    args = {"best_only":True}
    assert guard("Quels Pokémon Feu apprennent une attaque Eau spéciale d'au moins 80 de puissance ?",
                 "pokemon_search", args) is None
    assert not args["best_only"] and args["min_power"] == 80
    assert args["damage_class"] == "special" and args["types"] == ["fire"]
    args = {"best_only":True,"limit":1}
    assert guard("Quels sont les 5 Pokémon les plus rapides qui apprennent des capacités entre les niveaux 10 et 20 ?",
                 "pokemon_search", args) is None
    assert args["limit"] == 5 and not args["best_only"]
    assert (args["min_level"],args["max_level"]) == (10,20)


def test_more_than_two_pokemon_types_cannot_be_silently_shortened():
    args = {"types":["water","flying"]}
    assert guard("Pokémon de type Eau et Vol et Feu", "pokemon_search", args)["error"] == "invalid_explicit_constraints"
    assert args == {"types":["water","flying"]}


@pytest.mark.parametrize("question,name,args,expected", [
    ("Quelles capacités spéciales de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre ?", "pokemon_moves",
     {"pokemon":"Nigirigon","move_type":"water","min_power":80,"learning_method":"level-up"},
     {"pokemon":"Nigirigon","move_type":"water","damage_class":"special","min_power":80,"max_power":None}),
    ("Quels Pokémon peuvent apprendre une capacité de type Eau d'au moins 80 de puissance ?", "pokemon_search",
     {"move_type":"water","min_power":80,"learning_method":"machine"}, None),
])
def test_learning_method_absent_from_the_question_is_removed(question, name, args, expected):
    assert guard(question, name, args) is None
    assert "learning_method" not in args
    if expected is not None:
        assert args == expected


@pytest.mark.parametrize("question,method", [
    ("Quelles capacités Krakos apprend-il par CT ?", "machine"),
    ("Quelles capacités Krakos peut-il apprendre grâce à la CT12 ?", "machine"),
    ("Quelles capacités Krakos apprend-il par reproduction ?", "egg"),
    ("Quelles capacités œuf Krakos peut-il apprendre ?", "egg"),
    ("Quelles capacités Krakos apprend-il auprès d'un donneur de capacités ?", "tutor"),
    ("Quelles capacités Krakos apprend-il en montant de niveau ?", "level-up"),
    ("Par quelle méthode Krakos apprend-il ses capacités de type Eau ?", "tutor"),
    ("Comment Krakos apprend-il ses capacités de type Eau ?", "egg"),
])
def test_learning_method_is_kept_as_soon_as_the_question_mentions_a_method(question, method):
    args = {"pokemon":"Krakos","learning_method":method}
    assert guard(question, "pokemon_moves", args) is None
    assert args["learning_method"] == method


def test_level_bounds_still_force_level_up_after_the_method_check():
    args = {"pokemon":"Krakos"}
    assert guard("Quelles capacités Krakos apprend-il entre les niveaux 10 et 20 ?", "pokemon_moves", args) is None
    assert (args["learning_method"], args["min_level"], args["max_level"]) == ("level-up", 10, 20)


@pytest.mark.parametrize("question", [
    "Comment Krakos apprend-il Lance-Soleil ?",
    "Comment évolue Krakos avec une Pierre Lune ?",
    "Comment Krakos apprend-il Lune Rouge ?",
    "Combien d'EV donne Krakos ?",
    "Quels Pokémon de type Feu dans la première génération ?",
])
def test_a_game_word_inside_a_name_or_a_plain_dans_is_not_a_game(question):
    constraints = extract_explicit_constraints(question)
    assert (constraints.version_group, constraints.version_ambiguous, constraints.explicit_game) == (None, False, False)


@pytest.mark.parametrize("question,game", [
    ("Quelles CT Krakos apprend-il dans Pokémon Écarlate ?", "scarlet-violet"),
    ("Quelles CT Krakos apprend-il en Lune ?", "sun-moon"),
    ("Quelles CT Krakos apprend-il dans Soleil et Lune ?", "sun-moon"),
    ("Quelles CT Krakos apprend-il dans Épée/Bouclier ?", "sword-shield"),
    ("Quelles CT Krakos apprend-il dans Rouge Feu ?", "firered-leafgreen"),
    ("Quelles capacités Krakos apprend-il par Lance-Soleil dans Pokémon Soleil ?", "sun-moon"),
])
def test_a_named_game_keeps_its_constraint(question, game):
    assert extract_explicit_constraints(question).version_group == game


@pytest.mark.parametrize("question", ["Quelles CT dans Diamant, Perle et Platine ?",
                                      "Quelles CT Krakos apprend-il dans JeuInconnu ?"])
def test_several_or_unknown_named_games_stay_ambiguous(question):
    constraints = extract_explicit_constraints(question)
    assert constraints.version_group is None and constraints.version_ambiguous


@pytest.mark.parametrize("question,form", [
    ("Quels Pokémon viennent de Galar ?", None),
    ("Quels sont les starters de la région d'Alola ?", None),
    ("Quels Pokémon vivent en Hisui ?", None),
    ("Quelles sont les formes de Galar ?", "galar"),
    ("Quels sont les types de Krakos d'Alola ?", "alola"),
])
def test_a_region_is_a_form_only_when_it_qualifies_a_pokemon(question, form):
    assert extract_explicit_constraints(question).form == form


def test_a_region_as_a_place_adds_no_form_to_the_search():
    args = {"generation": 8}
    assert guard("Quels Pokémon viennent de Galar ?", "pokemon_search", args) is None
    assert "form" not in args


def test_placeholder_values_and_unrequested_filters_are_removed():
    # Arguments proposés par Qwen deux fois sur deux (trace 5e9464875496421f93c4a82c767b92d6).
    # Le stade est valide mais non demandé : « le fossile le plus rapide » au stade final excluait Ptéra.
    args = {"subgroup": "starter", "evolution_stage": "base", "talent": "none", "legendary": True}
    assert guard("Quels sont les types des starters de première génération ?", "pokemon_search", args) is None
    assert args == {"subgroup": "Starter", "generation": 1}


@pytest.mark.parametrize("question,stage", [
    ("Quel Pokémon sans évolution a le plus d'Attaque ?", "no-evolution"),
    ("Quels Pokémon Feu au stade final sont des fossiles ?", "final"),
    ("Quel est le fossile le plus rapide ?", None),
    ("Quel Pokémon a le meilleur total de statistiques de base ?", None),
])
def test_a_stage_needs_a_stage_word(question, stage):
    args = {"evolution_stage": stage or "final"}
    assert guard(question, "pokemon_search", args) is None
    assert args.get("evolution_stage") == stage


@pytest.mark.parametrize("question,subgroup", [
    ("Quelles sont les formes régionales de première génération ?", "Forme régionale"),
    ("Quels sont les oiseaux de début d'aventure ?", "Oiseau de début d’aventure"),
    ("Quels Pokémon sont dans le sous-groupe Ultra-Chimère ?", "Ultra-Chimère"),
    ("Quelles sont les évolutions de starter de type Feu ?", "Évolution de starter"),
    ("Quels sont les starters spéciaux ?", "Starter spécial"),
    ("Quels sont les starters de première génération ?", "Starter"),
])
def test_every_spreadsheet_subgroup_can_be_named(question, subgroup):
    args = {"subgroup": subgroup}
    assert guard(question, "pokemon_search", args) is None
    assert args["subgroup"] == subgroup


@pytest.mark.parametrize("question,expected", [
    ("Quels Pokémon légendaires ont le talent Lévitation ?", {"talent": "Lévitation", "legendary": True}),
    ("Quels Pokémon ont le talent Lévitation ?", {"talent": "Lévitation"}),
])
def test_a_named_talent_is_kept_and_a_classification_needs_its_word(question, expected):
    args = {"talent": "Lévitation", "legendary": True}
    assert guard(question, "pokemon_search", args) is None
    assert args == expected


@pytest.mark.parametrize("question,proposed,expected", [
    # Valeurs proposées sous LM Studio le 7 octobre : chacune faisait échouer toute la recherche.
    ("Quels Pokémon viennent de Galar ?", {"generation": 8, "subgroup": "Galar", "talent": "Galarian"},
     {"generation": 8}),
    ("Quels sont les 4 Pokémon les plus lents ?", {"subgroup": "base", "version_group": "ruby"}, {}),
])
def test_values_unjustified_by_the_question_are_removed(question, proposed, expected):
    assert guard(question, "pokemon_search", proposed) is None
    assert {key: proposed[key] for key in ("generation", "subgroup", "talent", "version_group") if key in proposed} == expected


def test_an_unknown_talent_named_by_the_question_is_kept_for_the_engine_refusal():
    args = {"talent": "Lévitaion"}
    assert guard("Quels Pokémon ont le talent Lévitaion ?", "pokemon_search", args) is None
    assert args["talent"] == "Lévitaion"


@pytest.mark.parametrize("question,limit", [
    ("Quels sont les Pokémon légendaires introduits en quatrième génération ?", None),
    ("Combien de Pokémon sont de type Spectre ?", 0),
])
def test_limit_zero_is_kept_only_for_a_counting_question(question, limit):
    args = {"generation": 4, "legendary": True, "limit": 0}
    assert guard(question, "pokemon_search", args) is None
    assert args.get("limit") == limit



@pytest.mark.parametrize("question,subgroup", [
    ("Quels starters au stade final sont de type Feu ?", "Évolution de starter"),
    ("Quelles sont les Méga des starters ?", "Évolution de starter"),
    ("Quels starters complètement évolués sont de type Eau ?", "Évolution de starter"),
    ("Quels starters évoluent au niveau 16 ?", "Starter"),
    ("Quel est le starter le plus rapide ?", "Starter"),
])
def test_a_starter_at_an_advanced_stage_is_a_starter_evolution(question, subgroup):
    # « Starter » ne désigne que le stade de base depuis la correction du tableur (7 octobre).
    from pokemon_rag.constraints.query_constraints import extract_subgroup
    assert extract_subgroup(question) == subgroup



@pytest.mark.parametrize("question,talent,kept", [
    # Réel, LM Studio, 7 octobre : « de type Feu » formait un talent `type_feu`, refusé trois fois.
    ("Quels starters au stade final sont de type Feu ?", "type_feu", False),
    ("Quels Pokémon ont Lévitation ?", "Lévitation", True),       # vrai talent cité sans le mot
    ("Quels Pokémon ont Lévitaion ?", "Lévitaion", False),        # faute de frappe sans le mot « talent »
])
def test_a_cited_value_justifies_a_talent_only_if_it_is_a_real_talent(monkeypatch, question, talent, kept):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.talent_names", lambda: frozenset({"levitation", "momie"}))
    args = {"talent": talent}
    assert guard(question, "pokemon_search", args) is None
    assert ("talent" in args) is kept
