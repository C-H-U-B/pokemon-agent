"""Le vocabulaire de la base ne doit pas devenir une contrainte : un nom n'est ni un jeu, ni une forme.

Risque : un mot de jeu ou de région contenu dans un nom (« Lance-Soleil », « Rugit-Lune »,
« Lune Rouge ») impose ou bloque un jeu, ou ajoute une forme, sans que la question en nomme.
Vrais noms français de pokemon.db ; extracteur commun aux trois parcours ; aucun LLM.
"""
import sqlite3
from contextlib import closing

import pytest

from pokemon_rag.config import DB_PATH
from pokemon_rag.constraints.query_constraints import extract_explicit_constraints, named_pokemon_mentions
from pokemon_rag.structured.query_engine import pokemon_name_catalogue, vocabulary_words

pytestmark = pytest.mark.real_data


def _french_names(*tables: str) -> list[str]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        fr = conn.execute("SELECT id FROM languages WHERE iso639='fr'").fetchone()[0]
        names = {row[0] for table in tables
                 for row in conn.execute(f"SELECT name FROM {table} WHERE local_language_id=?", (fr,)) if row[0]}
        names |= {row[0] for column in ("talent_1", "talent_2", "talent_cache")
                  for row in conn.execute(f"SELECT DISTINCT {column} FROM custom_pokedex_fr") if row[0]}
    return sorted(names)


def test_no_name_of_the_database_names_a_game():
    names = _french_names("pokemon_species_names", "move_names", "item_names", "location_names")
    wrong = [(name, constraints.version_group) for name in names
             if (constraints := extract_explicit_constraints(f"Que sais-tu de {name} ?")).version_group
             or constraints.version_ambiguous]
    assert len(names) > 5000
    assert wrong == []


def test_no_move_item_or_talent_name_adds_a_form():
    names = _french_names("move_names", "item_names")
    wrong = [name for name in names if extract_explicit_constraints(f"Que sais-tu de {name} ?").form]
    assert wrong == []


def test_every_subgroup_of_the_spreadsheet_is_recognised_by_its_own_name():
    # Un sous-groupe que l'extraction ne connaît pas ne peut pas être justifié : le guard le retirerait.
    # Fabuleux et Méga-Évolution passent par les filtres mythical et form_category.
    from pokemon_rag.constraints.query_constraints import extract_subgroup
    with closing(sqlite3.connect(DB_PATH)) as conn:
        subgroups = {part.strip() for (cell,) in conn.execute(
            "SELECT DISTINCT sous_groupe FROM custom_pokedex_fr WHERE sous_groupe IS NOT NULL")
            for part in cell.split(" ; ") if part.strip()} - {"Fabuleux", "Méga-Évolution"}
    assert {name for name in subgroups if extract_subgroup(f"Quels sont les {name} ?") != name} == set()


@pytest.mark.parametrize("question,expected", [
    ("en quoi évoluent carmache et mimigale ?", ["Carmache", "Mimigal"]),   # traces Web, six fois
    ("donne moi l'attaque de écoli et gouroutan", ["Évoli", "Gouroutan"]),  # traces Web, deux fois
    ("quel est le poids de ronflexx ?", ["Ronflex"]),
    ("Quels Pokémon apprennent Mimique ?", []),          # capacité, pas Mimiqui
    ("Qui a le talent Armure Miroir ?", []),             # talent, pas Airmure
    ("Capacités de type Eau dans Pokémon Diamant", []),  # jeu, pas Diamat
    ("Quel nombre de Pokémon Ombre ou Magma ?", []),     # ni Lombre ni Magmar
])
def test_one_typo_names_a_pokemon_but_the_vocabulary_of_the_database_does_not(question, expected):
    mentions = named_pokemon_mentions(question, pokemon_name_catalogue(), vocabulary_words())
    assert [mention["pokemon"] for mention in mentions] == expected
