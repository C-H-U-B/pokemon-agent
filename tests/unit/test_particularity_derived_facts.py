"""Rubriques de la fiche calculées depuis PokéAPI : types, anciens talents et statistiques, objets, Gigamax, jeux.

Base SQLite en mémoire, réduite aux tables lues. Le risque couvert est celui d'une rubrique fausse
servie comme un fait : multiplicateur mal combiné, table absente, jeu compté à tort comme une absence.
"""
import itertools
import sqlite3

import pytest

from pokemon_rag.constraints.query_constraints import VERSION_GROUP_NAMES_FR
from pokemon_rag.structured import query_engine as engine

WEAK, RESISTED, IMMUNE = "Faiblesses de type", "Résistances de type", "Immunités de type"
PAST_ABILITY, PAST_STATS, ITEMS = "Ancien talent", "Anciennes statistiques", "Objets tenus à l'état sauvage"
GIGANTAMAX, MISSING_GAMES = "Gigamax", "Jeux sans ce Pokémon depuis son introduction"

# Extrait de la table des types : identifiant PokéAPI, nom français, nom anglais.
TYPES = [(1, "Normal", "Normal"), (3, "Vol", "Flying"), (5, "Sol", "Ground"), (6, "Roche", "Rock"), (8, "Spectre", "Ghost"),
         (10, "Feu", "Fire"), (11, "Eau", "Water"), (12, "Plante", "Grass"), (13, "Électrik", "Electric")]
# (attaquant, cible) -> facteur ; toute autre paire vaut 100.
FACTORS = {("Normal", "Roche"): 50, ("Normal", "Spectre"): 0, ("Vol", "Plante"): 200, ("Vol", "Roche"): 50, ("Vol", "Électrik"): 50,
           ("Sol", "Vol"): 0, ("Sol", "Roche"): 200, ("Sol", "Feu"): 200, ("Sol", "Plante"): 50, ("Sol", "Électrik"): 200,
           ("Roche", "Vol"): 200, ("Roche", "Sol"): 50, ("Roche", "Feu"): 200, ("Spectre", "Normal"): 0, ("Spectre", "Spectre"): 200,
           ("Feu", "Roche"): 50, ("Feu", "Feu"): 50, ("Feu", "Eau"): 50, ("Feu", "Plante"): 200,
           ("Eau", "Sol"): 200, ("Eau", "Roche"): 200, ("Eau", "Feu"): 200, ("Eau", "Eau"): 50, ("Eau", "Plante"): 50,
           ("Plante", "Vol"): 50, ("Plante", "Sol"): 200, ("Plante", "Roche"): 200, ("Plante", "Feu"): 50, ("Plante", "Eau"): 200,
           ("Plante", "Plante"): 50, ("Électrik", "Vol"): 200, ("Électrik", "Sol"): 0, ("Électrik", "Eau"): 200,
           ("Électrik", "Plante"): 50, ("Électrik", "Électrik"): 50}
# identifiant, nom, génération, ordre de sortie. L'ordre ne suit pas l'identifiant (Rouge Feu, Champions),
# et trois groupes n'ont pas de libellé français : jeu annexe, extension, jeu sans movepool en base.
GROUPS = [(1, "red-blue", 1, 3), (5, "ruby-sapphire", 3, 7), (13, "xd", 3, 10), (7, "firered-leafgreen", 3, 11),
          (17, "sun-moon", 7, 19), (20, "sword-shield", 8, 22), (21, "the-isle-of-armor", 8, 23),
          (25, "scarlet-violet", 9, 27), (30, "legends-za", 9, 30), (32, "champions", 9, 32)]
GAME = VERSION_GROUP_NAMES_FR


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE language_ids(fr INTEGER, en INTEGER);
        INSERT INTO language_ids VALUES (5, 9);
        CREATE TABLE type_names(type_id INTEGER, local_language_id INTEGER, name TEXT);
        CREATE TABLE type_efficacy(damage_type_id INTEGER, target_type_id INTEGER, damage_factor INTEGER);
        CREATE TABLE ability_names(ability_id INTEGER, local_language_id INTEGER, name TEXT);
        INSERT INTO ability_names VALUES (26,5,'Lévitation'), (26,9,'Levitate'), (31,5,'Paratonnerre'), (9,5,'Statik'), (77,9,'Tangled Feet');
        CREATE TABLE pokemon_abilities_past(pokemon_id INTEGER, generation_id INTEGER, ability_id INTEGER, is_hidden INTEGER, slot INTEGER);
        CREATE TABLE pokemon_stats_past(pokemon_id INTEGER, generation_id INTEGER, stat_id INTEGER, base_stat INTEGER, effort INTEGER);
        CREATE TABLE item_names(item_id INTEGER, local_language_id INTEGER, name TEXT);
        INSERT INTO item_names VALUES (1,5,'Balle Lumière'), (1,9,'Light Ball'), (2,5,'Baie Oran'), (3,5,'Aimant'), (4,9,'Untranslated');
        CREATE TABLE versions(id INTEGER, version_group_id INTEGER, identifier TEXT);
        INSERT INTO versions VALUES (1,1,'red'), (2,1,'blue'), (7,5,'ruby'), (8,5,'sapphire'), (20,13,'xd'), (10,7,'firered'),
            (27,17,'sun'), (33,20,'sword'), (40,25,'scarlet');
        CREATE TABLE pokemon_items(pokemon_id INTEGER, version_id INTEGER, item_id INTEGER, rarity INTEGER);
        CREATE TABLE version_groups(id INTEGER, identifier TEXT, generation_id INTEGER, "order" INTEGER);
        CREATE TABLE pokemon(id INTEGER, identifier TEXT);
        INSERT INTO pokemon VALUES (25,'pikachu'), (10199,'pikachu-gmax'), (6,'charizard'), (10034,'charizard-mega-x'),
            (10196,'charizard-gmax'), (122,'mr-mime'), (10168,'mr-mime-galar'), (849,'toxtricity-amped'),
            (10219,'toxtricity-amped-gmax'), (1,'bulbasaur');
        CREATE TABLE pokemon_moves(pokemon_id INTEGER, version_group_id INTEGER);
    """)
    connection.executemany("INSERT INTO type_names VALUES (?,?,?)",
                           [row for identifier, fr, en in TYPES for row in ((identifier, 5, fr), (identifier, 9, en))])
    ids = {fr: identifier for identifier, fr, _ in TYPES}
    connection.executemany("INSERT INTO type_efficacy VALUES (?,?,?)",
                           [(ids[a], ids[t], FACTORS.get((a, t), 100)) for a in ids for t in ids])
    connection.executemany("INSERT INTO version_groups VALUES (?,?,?,?)", GROUPS)
    yield connection
    connection.close()


def _expected_matchups(type_1, type_2):
    """Calcul indépendant du SQL : produit des deux facteurs, rangé par rubrique dans l'ordre de la fiche."""
    marks = {400: " (×4)", 200: " (×2)", 50: " (×½)", 25: " (×¼)", 0: ""}
    products = [(FACTORS.get((fr, type_1), 100) * (FACTORS.get((fr, type_2), 100) if type_2 else 100) // 100, identifier, fr)
                for identifier, fr, _ in TYPES]
    ordered = sorted(products, key=lambda item: (-item[0], item[1]))
    groups = {WEAK: [fr + marks[f] for f, _, fr in ordered if f > 100], RESISTED: [fr + marks[f] for f, _, fr in ordered if 0 < f < 100],
              IMMUNE: [fr for f, _, fr in ordered if f == 0]}
    return {label: ", ".join(values) for label, values in groups.items() if values}


# --- Faiblesses, résistances, immunités ---

def test_single_type_lists_each_attacking_type_once_with_its_multiplier(conn):
    assert engine._type_matchups(conn, "Feu", None) == {
        WEAK: "Sol (×2), Roche (×2), Eau (×2)", RESISTED: "Feu (×½), Plante (×½)"}


def test_dual_type_multiplies_factors_instead_of_listing_each_type_separately(conn):
    facts = engine._type_matchups(conn, "Feu", "Vol")
    # Roche ×2 sur Feu et ×2 sur Vol ; Plante ×½ deux fois ; Électrik ×2 sur Vol seulement.
    assert facts[WEAK] == "Roche (×4), Eau (×2), Électrik (×2)"
    assert facts[RESISTED] == "Feu (×½), Plante (×¼)"


def test_an_immunity_of_one_type_cancels_the_weakness_of_the_other(conn):
    facts = engine._type_matchups(conn, "Feu", "Vol")
    assert facts[IMMUNE] == "Sol" and "Sol" not in facts[WEAK]  # Sol ×2 sur Feu, ×0 sur Vol


def test_a_weakness_and_a_resistance_cancel_out_and_are_not_listed(conn):
    facts = engine._type_matchups(conn, "Eau", "Sol")
    assert facts == {WEAK: "Plante (×4)", RESISTED: "Roche (×½), Feu (×½)", IMMUNE: "Électrik"}  # Eau ×½ et ×2 : neutre


def test_headings_without_any_type_are_left_out(conn):
    assert engine._type_matchups(conn, "Normal", None) == {IMMUNE: "Spectre"}
    assert WEAK not in engine._type_matchups(conn, "Normal", "Spectre")


def test_type_order_does_not_change_the_result(conn):
    assert engine._type_matchups(conn, "Feu", "Vol") == engine._type_matchups(conn, "Vol", "Feu")


def test_an_empty_second_type_is_a_single_type_not_an_unknown_one(conn):
    assert engine._type_matchups(conn, "Feu", "") == engine._type_matchups(conn, "Feu", None)


@pytest.mark.parametrize("type_1, type_2", [("Fire", None), ("feu", None), ("Inconnu", None), (None, None), ("", None)])
def test_a_type_name_that_is_not_the_exact_french_name_gives_no_heading(conn, type_1, type_2):
    # Comparaison exacte : ni nom anglais, ni casse différente, ni valeur vide ne retombent sur un type voisin.
    assert engine._type_matchups(conn, type_1, type_2) == {}


def test_an_unknown_second_type_is_not_computed_as_a_single_type(conn):
    # Sans cela, un second type mal saisi donnerait les faiblesses du seul premier type, fausses pour ce Pokémon.
    assert engine._type_matchups(conn, "Feu", "Inconnu") == {}


@pytest.mark.parametrize("type_1, type_2", [(fr, None) for _, fr, _ in TYPES]
                         + list(itertools.permutations([fr for _, fr, _ in TYPES], 2)))
def test_every_type_combination_matches_an_independent_computation(conn, type_1, type_2):
    facts = engine._type_matchups(conn, type_1, type_2)
    assert facts == _expected_matchups(type_1, type_2)
    listed = [entry.split(" (")[0] for value in facts.values() for entry in value.split(", ")]
    assert len(listed) == len(set(listed))  # un type attaquant n'est jamais dans deux rubriques


def test_type_headings_are_left_out_when_the_database_predates_the_type_chart(conn):
    conn.execute("DROP TABLE type_efficacy")
    assert engine._type_matchups(conn, "Feu", "Vol") == {}


def test_only_a_missing_table_is_tolerated(conn):
    with pytest.raises(sqlite3.OperationalError):
        engine._optional_rows(conn, "SELECT missing_column FROM type_names", ())
    assert engine._optional_rows(conn, "SELECT 1 FROM missing_table", ()) == []


# --- Anciens talents ---

def test_past_ability_is_dated_by_its_last_generation(conn):
    conn.execute("INSERT INTO pokemon_abilities_past VALUES (94,6,26,0,1)")
    assert engine._pokeapi_history(conn, 94)[PAST_ABILITY] == "Lévitation (jusqu'à la G6, changé en G7)"


def test_past_hidden_ability_is_marked_as_hidden(conn):
    conn.execute("INSERT INTO pokemon_abilities_past VALUES (145,5,31,1,3)")
    assert engine._pokeapi_history(conn, 145)[PAST_ABILITY] == "Paratonnerre (talent caché, jusqu'à la G5, changé en G6)"


def test_a_slot_that_did_not_exist_yet_is_not_a_past_ability(conn):
    # PokéAPI note par une ligne sans talent qu'un emplacement n'existait pas encore (talent caché avant la G5).
    conn.execute("INSERT INTO pokemon_abilities_past VALUES (1,4,NULL,1,3)")
    assert PAST_ABILITY not in engine._pokeapi_history(conn, 1)


def test_several_past_abilities_are_ordered_by_generation_then_slot(conn):
    conn.executemany("INSERT INTO pokemon_abilities_past VALUES (?,?,?,?,?)",
                     [(25, 6, 26, 0, 1), (25, 4, 31, 1, 3), (25, 4, 9, 0, 1), (25, 3, None, 0, 2)])
    assert engine._pokeapi_history(conn, 25)[PAST_ABILITY] == (
        "Statik (jusqu'à la G4, changé en G5) ; Paratonnerre (talent caché, jusqu'à la G4, changé en G5) ; Lévitation (jusqu'à la G6, changé en G7)")


def test_a_past_ability_without_french_name_is_left_out_rather_than_shown_in_english(conn):
    conn.execute("INSERT INTO pokemon_abilities_past VALUES (16,5,77,0,2)")
    assert PAST_ABILITY not in engine._pokeapi_history(conn, 16)


def test_past_abilities_of_another_pokemon_are_not_returned(conn):
    conn.execute("INSERT INTO pokemon_abilities_past VALUES (94,6,26,0,1)")
    assert PAST_ABILITY not in engine._pokeapi_history(conn, 93)


# --- Anciennes statistiques ---

def test_past_stat_names_follow_the_pokeapi_identifiers():
    assert engine.PAST_STAT_NAMES == {1: "PV", 2: "Attaque", 3: "Défense", 4: "Attaque Spéciale", 5: "Défense Spéciale",
                                      6: "Vitesse", 9: "Spécial"}


def test_past_stat_gives_the_old_value_and_its_last_generation(conn):
    conn.executemany("INSERT INTO pokemon_stats_past VALUES (25,?,?,?,0)", [(5, 5, 40), (5, 3, 30)])
    assert engine._pokeapi_history(conn, 25)[PAST_STATS] == "Défense : 30 (jusqu'à la G5) ; Défense Spéciale : 40 (jusqu'à la G5)"


def test_first_generation_special_is_named_and_not_dated_like_a_change(conn):
    conn.executemany("INSERT INTO pokemon_stats_past VALUES (12,?,?,?,0)", [(5, 4, 80), (1, 9, 80)])
    assert engine._pokeapi_history(conn, 12)[PAST_STATS] == "Spécial : 80 (G1 seulement) ; Attaque Spéciale : 80 (jusqu'à la G5)"


def test_a_stat_changed_twice_keeps_both_values_in_order(conn):
    conn.executemany("INSERT INTO pokemon_stats_past VALUES (7,?,?,?,0)", [(7, 2, 70), (4, 2, 60)])
    assert engine._pokeapi_history(conn, 7)[PAST_STATS] == "Attaque : 60 (jusqu'à la G4) ; Attaque : 70 (jusqu'à la G7)"


def test_a_stat_identifier_outside_the_known_ones_is_ignored(conn):
    conn.execute("INSERT INTO pokemon_stats_past VALUES (7,3,8,100,0)")  # 7 et 8 : précision et esquive
    assert PAST_STATS not in engine._pokeapi_history(conn, 7)


# --- Objets tenus à l'état sauvage ---

def test_held_item_gives_rarity_and_generation(conn):
    conn.execute("INSERT INTO pokemon_items VALUES (81,7,3,5)")
    assert engine._pokeapi_history(conn, 81)[ITEMS] == "Aimant (5 %, G3)"


def test_held_item_merges_versions_into_ranges_and_sorts_by_highest_rarity(conn):
    conn.executemany("INSERT INTO pokemon_items VALUES (25,?,?,?)",
                     [(7, 1, 5), (8, 1, 5), (27, 1, 1), (7, 2, 50), (10, 2, 50)])
    assert engine._pokeapi_history(conn, 25)[ITEMS] == "Baie Oran (50 %, G3), Balle Lumière (1 à 5 %, G3–G7)"


def test_items_of_equal_rarity_are_sorted_by_name(conn):
    conn.executemany("INSERT INTO pokemon_items VALUES (25,7,?,5)", [(3,), (1,)])
    assert engine._pokeapi_history(conn, 25)[ITEMS] == "Aimant (5 %, G3), Balle Lumière (5 %, G3)"


def test_held_items_of_a_side_game_are_not_counted(conn):
    # XD donne des objets à 100 % : mêlés aux jeux principaux, ils fausseraient la rareté.
    conn.executemany("INSERT INTO pokemon_items VALUES (25,?,1,?)", [(7, 5), (20, 100)])
    assert engine._pokeapi_history(conn, 25)[ITEMS] == "Balle Lumière (5 %, G3)"
    conn.execute("INSERT INTO pokemon_items VALUES (113,20,2,100)")
    assert ITEMS not in engine._pokeapi_history(conn, 113)


def test_a_held_item_without_french_name_is_left_out(conn):
    conn.execute("INSERT INTO pokemon_items VALUES (25,7,4,5)")
    assert ITEMS not in engine._pokeapi_history(conn, 25)


# --- Gigamax ---

@pytest.mark.parametrize("pokemon_id, expected", [
    (25, True), (6, True), (849, True),      # la forme Gigamax porte l'identifiant de la forme, suffixé
    (10034, False),                          # une Méga-Évolution n'hérite pas du Gigamax de son espèce
    (10199, False),                          # la forme Gigamax elle-même
    (122, False), (10168, False), (1, False),
])
def test_gigantamax_is_read_from_the_form_of_the_exact_entry(conn, pokemon_id, expected):
    facts = engine._pokeapi_history(conn, pokemon_id)
    assert (facts.get(GIGANTAMAX) == "Forme Gigamax dans Pokémon Épée et Bouclier") is expected
    assert (GIGANTAMAX in facts) is expected


# --- Jeux sans ce Pokémon ---

def _learns_in(conn, pokemon_id, *groups):
    ids = {identifier: group_id for group_id, identifier, _, _ in GROUPS}
    conn.executemany("INSERT INTO pokemon_moves VALUES (?,?)", [(pokemon_id, ids[group]) for group in groups])


def test_a_pokemon_in_every_game_since_its_introduction_says_none(conn):
    _learns_in(conn, 25, "red-blue", "ruby-sapphire", "firered-leafgreen", "sun-moon", "sword-shield", "scarlet-violet", "champions")
    assert engine._pokeapi_history(conn, 25)[MISSING_GAMES] == "aucun"


def test_games_without_any_move_after_the_introduction_are_listed_in_release_order(conn):
    _learns_in(conn, 23, "red-blue", "ruby-sapphire", "sun-moon", "scarlet-violet")
    assert engine._pokeapi_history(conn, 23)[MISSING_GAMES] == " ; ".join(
        (GAME["firered-leafgreen"], GAME["sword-shield"], GAME["champions"]))


def test_games_released_before_the_introduction_are_not_absences(conn):
    _learns_in(conn, 722, "sun-moon", "sword-shield", "scarlet-violet", "champions")
    assert engine._pokeapi_history(conn, 722)[MISSING_GAMES] == "aucun"


def test_release_order_is_used_not_the_group_identifier(conn):
    # Rouge Feu et Vert Feuille (identifiant 7) sort après Rubis et Saphir (identifiant 5 … ordre 11 contre 7) :
    # un Pokémon apparu dans Rouge Feu n'est pas « absent » de Rubis et Saphir.
    _learns_in(conn, 386, "firered-leafgreen", "sun-moon", "sword-shield", "scarlet-violet", "champions")
    assert engine._pokeapi_history(conn, 386)[MISSING_GAMES] == "aucun"


def test_side_games_expansions_and_games_without_movepool_are_never_listed(conn):
    _learns_in(conn, 25, "red-blue", "ruby-sapphire", "firered-leafgreen", "sun-moon", "sword-shield", "scarlet-violet", "champions")
    value = engine._pokeapi_history(conn, 25)[MISSING_GAMES]  # ni XD, ni Isolarmure, ni Légendes Z-A
    assert value == "aucun"


def test_a_pokemon_known_only_in_a_side_game_gets_no_heading(conn):
    _learns_in(conn, 999, "xd")
    assert MISSING_GAMES not in engine._pokeapi_history(conn, 999)


def test_a_pokemon_without_any_movepool_gets_no_heading_rather_than_every_game(conn):
    assert MISSING_GAMES not in engine._pokeapi_history(conn, 10034)


def test_moves_of_another_pokemon_do_not_count(conn):
    _learns_in(conn, 25, "red-blue", "sword-shield")
    _learns_in(conn, 26, "red-blue", "ruby-sapphire", "firered-leafgreen", "sun-moon", "scarlet-violet", "champions")
    assert engine._pokeapi_history(conn, 26)[MISSING_GAMES] == GAME["sword-shield"]


def test_every_listed_game_has_a_french_label(conn):
    labelled = {identifier for _, identifier, _, _ in GROUPS} & set(GAME)
    _learns_in(conn, 25, "red-blue")
    listed = engine._pokeapi_history(conn, 25)[MISSING_GAMES].split(" ; ")
    assert listed == [GAME[identifier] for _, identifier, _, _ in sorted(GROUPS, key=lambda group: group[3])
                      if identifier in labelled and identifier != "red-blue"]


# --- Fiche entière ---

def test_history_headings_are_left_out_when_the_database_predates_them(conn):
    conn.executescript("DROP TABLE pokemon_abilities_past; DROP TABLE pokemon_stats_past; DROP TABLE pokemon_items; DROP TABLE ability_names;")
    _learns_in(conn, 25, "red-blue", "sword-shield")
    assert set(engine._pokeapi_history(conn, 25)) == {GIGANTAMAX, MISSING_GAMES}


def test_headings_keep_a_fixed_order_and_empty_ones_are_omitted(conn):
    conn.execute("INSERT INTO pokemon_abilities_past VALUES (25,6,26,0,1)")
    conn.execute("INSERT INTO pokemon_stats_past VALUES (25,5,3,30,0)")
    conn.execute("INSERT INTO pokemon_items VALUES (25,7,1,5)")
    _learns_in(conn, 25, "red-blue")
    assert list(engine._pokeapi_history(conn, 25)) == [PAST_ABILITY, PAST_STATS, ITEMS, GIGANTAMAX, MISSING_GAMES]
    assert engine._pokeapi_history(conn, 1) == {}


def test_the_tool_description_announces_the_new_headings_in_the_part_the_model_receives():
    # Le modèle ne reçoit que le premier paragraphe, coupé à 300 caractères : une rubrique annoncée
    # plus bas n'est jamais demandée (« Ronflex pèse 160 » lu dans les statistiques de base).
    import inspect

    from pokemon_rag.agent.context_budget import _abridged_description
    from pokemon_rag.mcp import server

    full = inspect.getdoc(server.pokemon_particularities).split("\n\n", 1)[0]
    received = _abridged_description(inspect.getdoc(server.pokemon_particularities))
    assert received == full, f"premier paragraphe tronqué : {len(full)} caractères"
    for cue in ("anciens", "faiblesses et résistances", "modifiées", "objets tenus", "Gigamax", "absent",
                "taille", "poids", "taux de capture", "rangs", "baisse en évoluant", "obtention"):
        assert cue in received, cue


# --- Talents d'immunité : Sol pour Lévitation, Eau pour Absorbe-Eau, Électrik pour Paratonnerre et Motorisé ---

def test_a_type_cancelled_by_the_only_ability_leaves_the_weaknesses_and_becomes_an_immunity(conn):
    facts = engine._type_matchups(conn, "Feu", None, ("Lévitation", None, None))
    assert facts[WEAK] == "Roche (×2), Eau (×2)"  # plus de faiblesse au Sol
    assert facts[IMMUNE] == "Sol (talent Lévitation)"


def test_a_type_cancelled_by_one_ability_among_several_keeps_its_multiplier_and_names_the_ability(conn):
    facts = engine._type_matchups(conn, "Feu", None, ("Lévitation", "Brasier", None))
    assert facts[WEAK] == "Sol (×2 ; immunisé seulement s'il a le talent Lévitation), Roche (×2), Eau (×2)"
    assert IMMUNE not in facts  # l'immunité n'est pas acquise : elle dépend du talent de l'individu


def test_the_hidden_ability_counts_as_one_of_the_abilities(conn):
    hidden_only = engine._type_matchups(conn, "Électrik", None, ("Statik", None, "Paratonnerre"))
    assert hidden_only[RESISTED] == "Vol (×½), Électrik (×½ ; immunisé seulement s'il a le talent Paratonnerre)"
    assert engine._type_matchups(conn, "Feu", None, ("Brasier", None, "Lévitation"))[WEAK].startswith("Sol (×2 ; immunisé")


def test_a_resisted_type_cancelled_by_one_ability_is_annotated_in_the_resistances(conn):
    facts = engine._type_matchups(conn, "Eau", None, ("Absorbe-Eau", None, "Hydratation"))
    assert facts[RESISTED] == "Feu (×½), Eau (×½ ; immunisé seulement s'il a le talent Absorbe-Eau)"


def test_a_neutral_type_cancelled_by_one_ability_is_listed_as_a_conditional_immunity(conn):
    facts = engine._type_matchups(conn, "Normal", None, ("Anticipation", "Absorbe-Eau", "Toxitouche"))
    assert facts == {IMMUNE: "Eau (seulement s'il a le talent Absorbe-Eau), Spectre"}


def test_a_neutral_type_cancelled_by_every_ability_is_a_plain_ability_immunity(conn):
    assert engine._type_matchups(conn, "Normal", None, ("Absorbe-Eau", None, None)) == {IMMUNE: "Eau (talent Absorbe-Eau), Spectre"}


def test_two_abilities_cancelling_the_same_type_are_both_named_in_slot_order(conn):
    two_of_three = engine._type_matchups(conn, "Électrik", None, ("Paratonnerre", "Motorisé", "Herbivore"))
    assert "Électrik (×½ ; immunisé seulement s'il a le talent Paratonnerre ou Motorisé)" in two_of_three[RESISTED]
    assert two_of_three[IMMUNE] == "Plante (seulement s'il a le talent Herbivore)"
    reversed_slots = engine._type_matchups(conn, "Électrik", None, ("Motorisé", "Paratonnerre", "Herbivore"))
    assert "talent Motorisé ou Paratonnerre" in reversed_slots[RESISTED]


def test_every_ability_cancelling_the_same_type_makes_it_unconditional(conn):
    facts = engine._type_matchups(conn, "Électrik", None, ("Paratonnerre", "Motorisé", None))
    assert facts[IMMUNE] == "Électrik (talent Paratonnerre ou Motorisé)" and "Électrik" not in facts[RESISTED]


def test_an_ability_immunity_does_not_duplicate_an_immunity_of_type(conn):
    # Vol annule déjà le Sol : Lévitation n'ajoute ni doublon ni mention.
    assert engine._type_matchups(conn, "Feu", "Vol", ("Lévitation", None, None))[IMMUNE] == "Sol"
    assert engine._type_matchups(conn, "Feu", "Vol", ("Lévitation", "Brasier", None))[IMMUNE] == "Sol"


def test_an_ability_cancels_a_quadruple_weakness_too(conn):
    facts = engine._type_matchups(conn, "Feu", "Roche", ("Lévitation", None, None))
    assert "Sol" not in facts[WEAK] and "Sol (talent Lévitation)" in facts[IMMUNE]
    conditional = engine._type_matchups(conn, "Feu", "Roche", ("Lévitation", "Fermeté", None))
    assert "Sol (×4 ; immunisé seulement s'il a le talent Lévitation)" in conditional[WEAK]


@pytest.mark.parametrize("abilities", [(), (None, None, None), ("", "", ""), ("Brasier", None, "Force Soleil"),
                                       ("lévitation", None, None), ("Levitate", None, None), ("Isograisse", None, None)])
def test_abilities_that_cancel_no_type_change_nothing(conn, abilities):
    # Ni nom anglais, ni casse différente, ni talent qui réduit sans annuler.
    assert engine._type_matchups(conn, "Feu", None, abilities) == engine._type_matchups(conn, "Feu", None)


def test_ability_immunities_do_not_rescue_an_unknown_type(conn):
    assert engine._type_matchups(conn, "Inconnu", None, ("Lévitation", None, None)) == {}
    assert engine._type_matchups(conn, "Feu", "Inconnu", ("Lévitation", None, None)) == {}


@pytest.mark.parametrize("ability, cancelled", sorted(engine.ABILITY_IMMUNITIES.items()))
def test_every_listed_ability_cancels_exactly_its_type(conn, ability, cancelled):
    known = {fr for _, fr, _ in TYPES}
    if cancelled not in known:
        pytest.skip(f"{cancelled} hors de l'extrait de la table des types")
    for type_1 in known:
        facts = engine._type_matchups(conn, type_1, None, (ability, None, None))
        plain = engine._type_matchups(conn, type_1, None)
        by_type = cancelled in plain.get(IMMUNE, "").split(", ")
        assert (f"{cancelled} (talent {ability})" in facts.get(IMMUNE, "")) is not by_type, (type_1, facts)
        # Les autres types gardent leur rubrique et leur multiplicateur.
        strip = lambda value: [entry for entry in value.split(", ") if not entry.startswith(cancelled)]
        assert {label: strip(value) for label, value in facts.items() if strip(value)} == \
            {label: strip(value) for label, value in plain.items() if strip(value)}
