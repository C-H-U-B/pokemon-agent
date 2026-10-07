"""Le vocabulaire de la base ne doit pas devenir une contrainte : un nom n'est ni un jeu, ni une forme.

Risque : un mot de jeu ou de région contenu dans un nom (« Lance-Soleil », « Rugit-Lune »,
« Lune Rouge ») impose ou bloque un jeu, ou ajoute une forme, sans que la question en nomme.
Vrais noms français de pokemon.db ; extracteur commun aux trois parcours ; aucun LLM.
"""
import sqlite3
from contextlib import closing

import pytest

from pokemon_rag.config import DB_PATH
from pokemon_rag.constraints.query_constraints import extract_explicit_constraints

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
