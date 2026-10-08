"""Rubriques calculées de la fiche sur la vraie base : faits connus et invariants sur les 1 275 lignes.

Sans LLM. Exige le second lot PokéAPI (`type_efficacy`, `pokemon_abilities_past`, `pokemon_stats_past`,
`pokemon_items`, `ability_names`) : sur une base construite avant lui, ces tests échouent, la fiche non.
"""
import json
from contextlib import closing

import pytest

from pokemon_rag.agent.context_budget import MAX_TOOL_RESULT_BYTES
from pokemon_rag.constraints.query_constraints import VERSION_GROUP_NAMES_FR
from pokemon_rag.structured import query_engine as engine

pytestmark = pytest.mark.real_data

WEAK, RESISTED, IMMUNE = "Faiblesses de type", "Résistances de type", "Immunités de type"
PAST_ABILITY, PAST_STATS, ITEMS = "Ancien talent", "Anciennes statistiques", "Objets tenus à l'état sauvage"
GIGANTAMAX, MISSING_GAMES = "Gigamax", "Jeux sans ce Pokémon depuis son introduction"
GAME = VERSION_GROUP_NAMES_FR
MARKS = {400: " (×4)", 200: " (×2)", 50: " (×½)", 25: " (×¼)", 0: ""}


def sheet(pokemon):
    return engine.get_particularities(pokemon)["rows"][0]


@pytest.fixture(scope="module")
def conn():
    with closing(engine._connect()) as connection:
        yield connection


@pytest.fixture(scope="module")
def spreadsheet_rows(conn):
    return conn.execute("SELECT nom, type_1, type_2, pokemon_id FROM custom_pokedex_fr").fetchall()


# --- Faits connus ---

@pytest.mark.parametrize("pokemon, weak, resisted, immune", [
    ("Dracaufeu", "Roche (×4), Eau (×2), Électrik (×2)",
     "Combat (×½), Acier (×½), Feu (×½), Fée (×½), Insecte (×¼), Plante (×¼)", "Sol"),
    ("Ténéfix", "Fée (×2)", "Poison (×½)", "Normal, Combat, Psy"),          # une seule faiblesse, trois immunités
    ("Raichu d’Alola", "Sol (×2), Insecte (×2), Spectre (×2), Ténèbres (×2)",     # aucun talent d'immunité
     "Combat (×½), Vol (×½), Acier (×½), Électrik (×½), Psy (×½)", None),
    # Talent caché seul à annuler l'Électrik : le multiplicateur reste, le talent est nommé.
    ("Pikachu", "Sol (×2)", "Vol (×½), Acier (×½), Électrik (×½ ; immunisé seulement s'il a le talent Paratonnerre)", None),
    # Seul talent de la fiche : le Sol quitte les faiblesses.
    ("Fantominus", "Spectre (×2), Psy (×2), Ténèbres (×2)", "Plante (×½), Fée (×½), Poison (×¼), Insecte (×¼)",
     "Sol (talent Lévitation), Normal, Combat"),
    # Un talent sur trois : la faiblesse au Sol reste, annotée.
    ("Smogogo", "Sol (×2 ; immunisé seulement s'il a le talent Lévitation), Psy (×2)",
     "Combat (×½), Poison (×½), Insecte (×½), Plante (×½), Fée (×½)", None),
    # Type neutre annulé par un talent sur trois : immunité conditionnelle.
    ("Coatox", "Psy (×4), Vol (×2), Sol (×2)",
     "Combat (×½), Poison (×½), Roche (×½), Plante (×½), Ténèbres (×½), Insecte (×¼)", "Eau (seulement s'il a le talent Peau Sèche)"),
    ("Primo-Groudon", "Sol (×2)", "Poison (×½), Insecte (×½), Acier (×½), Feu (×½), Fée (×½)", "Eau (talent Terre Finale), Électrik"),
    ("Leveinard", "Combat (×2)", None, "Spectre"),                           # aucune résistance
    ("Méga-Dracaufeu X", "Sol (×2), Roche (×2), Dragon (×2)",                # types de la forme, pas de l'espèce
     "Insecte (×½), Acier (×½), Électrik (×½), Feu (×¼), Plante (×¼)", None),
    ("Feunard d’Alola", "Acier (×4), Poison (×2), Roche (×2), Feu (×2)", "Insecte (×½), Glace (×½), Ténèbres (×½)", "Dragon"),
])
def test_type_matchups_of_known_pokemon(pokemon, weak, resisted, immune):
    facts = sheet(pokemon)
    assert (facts.get(WEAK), facts.get(RESISTED), facts.get(IMMUNE)) == (weak, resisted, immune)


def test_past_abilities_of_known_pokemon():
    assert sheet("Ectoplasma")[PAST_ABILITY] == "Lévitation (jusqu'à la G6, changé en G7)"
    assert sheet("Électhor")[PAST_ABILITY] == "Paratonnerre (talent caché, jusqu'à la G5, changé en G6)"
    assert sheet("Ectoplasma")["Talent 1"] == "Corps Maudit"  # l'ancien talent ne remplace pas l'actuel
    assert PAST_ABILITY not in sheet("Tortank")  # talent caché inexistant avant la G5 : pas un ancien talent
    assert PAST_ABILITY not in sheet("Dracaufeu")


def test_past_stats_of_known_pokemon():
    assert sheet("Pikachu")[PAST_STATS] == (
        "Spécial : 50 (G1 seulement) ; Défense : 30 (jusqu'à la G5) ; Défense Spéciale : 40 (jusqu'à la G5)")
    assert sheet("Mewtwo")[PAST_STATS] == "Spécial : 154 (G1 seulement)"
    assert PAST_STATS not in sheet("Poussacha")
    assert PAST_STATS not in sheet("Méga-Dracaufeu X")  # le Spécial de la G1 n'est pas reporté sur une forme postérieure


def test_held_items_of_known_pokemon():
    assert sheet("Pikachu")[ITEMS] == "Baie Oran (50 %, G3–G5), Balle Lumière (1 à 5 %, G3–G7)"
    # Sans les jeux annexes : XD donne le Poing Chance à 100 %.
    assert sheet("Leveinard")[ITEMS] == "Pierre Ovale (50 %, G4), Poing Chance (50 %, G5–G7), Œuf Chance (5 %, G3–G6)"
    assert ITEMS not in sheet("Mewtwo")


def test_gigantamax_of_known_pokemon():
    assert sheet("Dracaufeu")[GIGANTAMAX] == "Forme Gigamax dans Pokémon Épée et Bouclier"
    assert GIGANTAMAX in sheet("Shifours Style Mille Poings") and GIGANTAMAX in sheet("Shifours Style Poing Final")
    for pokemon in ("Méga-Dracaufeu X", "Abo", "Raichu", "Poussacha"):
        assert GIGANTAMAX not in sheet(pokemon), pokemon


def test_missing_games_of_known_pokemon():
    missing = lambda pokemon: sheet(pokemon)[MISSING_GAMES].split(" ; ")
    assert missing("Pikachu") == ["aucun"]
    abo = missing("Abo")
    assert GAME["sword-shield"] in abo and GAME["scarlet-violet"] not in abo
    rattata = missing("Rattata")
    assert GAME["sword-shield"] in rattata and GAME["scarlet-violet"] in rattata and GAME["sun-moon"] not in rattata
    assert GAME["legends-arceus"] in missing("Dracaufeu") and GAME["sword-shield"] not in missing("Dracaufeu")
    # Une Méga-Évolution disparaît avec la huitième génération ; les jeux d'avant la sixième ne sont pas des absences.
    mega = missing("Méga-Dracaufeu X")
    assert GAME["sword-shield"] in mega and GAME["scarlet-violet"] in mega
    assert GAME["black-white"] not in mega and GAME["x-y"] not in mega
    # Forme de Noir 2 et Blanc 2 : Noir et Blanc, sorti avant, n'est pas une absence.
    assert GAME["black-white"] not in missing("Boréas Totémique")
    assert MISSING_GAMES not in sheet("Méga-Lucario Z")  # aucun movepool en base : rien ne se déduit


# --- Invariants sur toutes les lignes du tableur ---

def test_every_sheet_matches_an_independent_reading_of_the_type_chart(conn, spreadsheet_rows):
    names = dict(conn.execute("SELECT name, type_id FROM type_names WHERE local_language_id = (SELECT fr FROM language_ids)"))
    labels = {identifier: name for name, identifier in names.items()}
    chart = {(a, t): f for a, t, f in conn.execute("SELECT damage_type_id, target_type_id, damage_factor FROM type_efficacy")}
    attackers = sorted({a for a, _ in chart})
    assert len(attackers) == 18 and len(chart) == 324
    seen = set()
    for row in spreadsheet_rows:
        key = (row["type_1"], row["type_2"])
        if key in seen:
            continue
        seen.add(key)
        factors = [(chart[a, names[key[0]]] * (chart[a, names[key[1]]] if key[1] else 100) // 100, a) for a in attackers]
        ordered = sorted(factors, key=lambda item: (-item[0], item[1]))
        expected = {WEAK: [labels[a] + MARKS[f] for f, a in ordered if f > 100],
                    RESISTED: [labels[a] + MARKS[f] for f, a in ordered if 0 < f < 100],
                    IMMUNE: [labels[a] for f, a in ordered if f == 0]}
        expected = {label: ", ".join(values) for label, values in expected.items() if values}
        assert engine._type_matchups(conn, *key) == expected, key
        assert engine._type_matchups(conn, key[1], key[0]) == expected if key[1] else True, key
        assert WEAK in expected, key  # aucune combinaison existante n'est sans faiblesse
    assert len(seen) > 150


def test_ability_immunities_only_move_the_type_they_cancel(conn):
    rows = conn.execute("SELECT nom, type_1, type_2, talent_1, talent_2, talent_cache FROM custom_pokedex_fr").fetchall()
    known = {name for name, in conn.execute("SELECT talent_1 FROM custom_pokedex_fr UNION SELECT talent_2 FROM custom_pokedex_fr "
                                            "UNION SELECT talent_cache FROM custom_pokedex_fr")}
    # Un talent renommé dans le tableur cesserait d'être reconnu sans que rien n'échoue.
    assert set(engine.ABILITY_IMMUNITIES) <= known, set(engine.ABILITY_IMMUNITIES) - known
    touched = 0
    for row in rows:
        abilities = tuple(row)[3:]
        cancelled = {engine.ABILITY_IMMUNITIES[ability] for ability in abilities if ability in engine.ABILITY_IMMUNITIES}
        plain, facts = engine._type_matchups(conn, row["type_1"], row["type_2"]), engine._type_matchups(conn, row["type_1"], row["type_2"], abilities)
        entries = [entry for value in facts.values() for entry in value.split(", ")]
        types = [entry.split(" (")[0] for entry in entries]
        assert len(types) == len(set(types)), (row["nom"], facts)  # un type n'est jamais dans deux rubriques
        keep = lambda value: [entry for entry in value.split(", ") if entry.split(" (")[0] not in cancelled]
        assert {label: keep(value) for label, value in facts.items() if keep(value)} == \
            {label: keep(value) for label, value in plain.items() if keep(value)}, row["nom"]
        if not cancelled:
            assert facts == plain, row["nom"]
        for kind in cancelled - set(plain.get(IMMUNE, "").split(", ")):
            granting = [ability for ability in abilities if engine.ABILITY_IMMUNITIES.get(ability) == kind]
            every = len(granting) == len([ability for ability in abilities if ability])
            entry = next(entry for entry in entries if entry.startswith(kind + " ("))
            assert all(ability in entry for ability in granting), (row["nom"], entry)
            assert (entry in facts.get(IMMUNE, "").split(", ") and "seulement" not in entry) is every or \
                ("seulement s'il a" in entry and not every), (row["nom"], entry)
            touched += 1
    assert touched > 100


def test_every_sheet_history_is_well_formed(conn, spreadsheet_rows):
    games, counts = set(GAME.values()), dict.fromkeys((PAST_ABILITY, PAST_STATS, ITEMS, GIGANTAMAX, MISSING_GAMES), 0)
    for row in spreadsheet_rows:
        if row["pokemon_id"] is None:
            continue
        facts = engine._pokeapi_history(conn, row["pokemon_id"])
        for label in facts:
            counts[label] += 1
        assert all(value and "None" not in value for value in facts.values()), (row["nom"], facts)
        listed = facts.get(MISSING_GAMES, "aucun").split(" ; ")
        assert listed == ["aucun"] or (set(listed) <= games and len(listed) == len(set(listed))), (row["nom"], listed)
    # Chaque rubrique existe réellement dans la base, sans devenir la règle (Gigamax, ancien talent).
    assert all(counts.values()), counts
    assert counts[GIGANTAMAX] < 40 and counts[PAST_ABILITY] < 100 and counts[MISSING_GAMES] > 1200, counts


def test_every_game_with_a_french_label_has_movepools(conn):
    # Sinon ce jeu serait compté comme une absence pour tous les Pokémon.
    without = [identifier for identifier in GAME if conn.execute(
        """SELECT 1 FROM pokemon_moves moves JOIN version_groups groups ON groups.id = moves.version_group_id
           WHERE groups.identifier = ? LIMIT 1""", (identifier,)).fetchone() is None]
    assert without == []


def test_no_sheet_outgrows_the_tool_result_budget(conn, spreadsheet_rows):
    largest = (0, None)
    for name in {row["nom"] for row in spreadsheet_rows}:
        try:
            facts = sheet(name)
        except ValueError:  # nom porté par plusieurs lignes (Nidoran, Vrombotor) : la forme doit être précisée
            continue
        largest = max(largest, (len(json.dumps(facts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), name))
    assert 0 < largest[0] < MAX_TOOL_RESULT_BYTES, largest


def test_derived_headings_come_after_the_spreadsheet_and_before_the_measures():
    labels = list(sheet("Pikachu"))
    assert labels.index("Talent 1") < labels.index(WEAK) < labels.index(PAST_STATS) < labels.index(ITEMS) \
        < labels.index(GIGANTAMAX) < labels.index(MISSING_GAMES) < labels.index("Taille")
