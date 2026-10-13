from __future__ import annotations

import runpy
import sqlite3
from pathlib import Path

import pytest
pytestmark = pytest.mark.real_data

from pokemon_rag.config import DB_PATH

_builder = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/pokeapi/build_pokeapi_db.py"))
REFERENCES, orphans = _builder["REFERENCES"], _builder["orphans"]


EXPECTED_OBJECTS = {
    "pokemon",
    "pokemon_species",
    "pokemon_forms",
    "pokemon_moves",
    "moves",
    "machines",
    "pokemon_evolution",
    "custom_pokedex_fr",
    "custom_pokedex_en",
    "custom_pokedex",
    "custom_pokeapi_mapping",
}


@pytest.fixture
def db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.fail(f"Base introuvable : {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")

    try:
        yield conn
    finally:
        conn.close()


def scalar(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple = (),
):
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def test_database_integrity(db: sqlite3.Connection) -> None:
    assert scalar(db, "PRAGMA integrity_check") == "ok"


def test_required_tables_and_views_exist(db: sqlite3.Connection) -> None:
    objects = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }

    missing = EXPECTED_OBJECTS - objects
    assert not missing, f"Objets SQLite manquants : {sorted(missing)}"


@pytest.mark.parametrize(
    "table",
    [
        "pokemon",
        "pokemon_species",
        "pokemon_forms",
        "pokemon_moves",
        "moves",
        "pokemon_evolution",
        "custom_pokedex_fr",
        "custom_pokedex_en",
        "custom_pokedex",
        "custom_pokeapi_mapping",
    ],
    ids=[
        "pokemon",
        "species",
        "forms",
        "pokemon-moves",
        "moves",
        "evolutions",
        "custom-fr",
        "custom-en",
        "custom-bilingual",
        "custom-mapping",
    ],
)
def test_core_objects_are_not_empty(
    db: sqlite3.Connection,
    table: str,
) -> None:
    assert scalar(db, f'SELECT COUNT(*) FROM "{table}"') > 0


def test_custom_pokedex_fr_and_en_have_same_row_count(
    db: sqlite3.Connection,
) -> None:
    fr = scalar(db, "SELECT COUNT(*) FROM custom_pokedex_fr")
    en = scalar(db, "SELECT COUNT(*) FROM custom_pokedex_en")

    assert fr == en
    assert fr > 0


def test_custom_pokedex_source_rows_are_unique(
    db: sqlite3.Connection,
) -> None:
    for table in ("custom_pokedex_fr", "custom_pokedex_en"):
        duplicates = scalar(
            db,
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT source_row
                FROM "{table}"
                GROUP BY source_row
                HAVING COUNT(*) > 1
            )
            """,
        )

        assert duplicates == 0, f"source_row dupliqué dans {table}"


@pytest.mark.parametrize("reference", REFERENCES, ids=lambda r: f"{r[0]}.{r[1]}")
def test_references_are_not_orphaned(db: sqlite3.Connection, reference: tuple) -> None:
    # Même liste et même requête que le contrôle fait à la construction de la base.
    assert orphans(db, [reference]) == []


def test_default_pokemon_are_unique_per_species(
    db: sqlite3.Connection,
) -> None:
    duplicates = db.execute(
        """
        SELECT species_id, COUNT(*) AS count
        FROM pokemon
        WHERE is_default = 1
        GROUP BY species_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    assert duplicates == []


def test_pokemon_identifiers_are_unique(
    db: sqlite3.Connection,
) -> None:
    duplicates = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM (
            SELECT identifier
            FROM pokemon
            GROUP BY identifier
            HAVING COUNT(*) > 1
        )
        """,
    )

    assert duplicates == 0


def test_species_identifiers_are_unique(
    db: sqlite3.Connection,
) -> None:
    duplicates = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM (
            SELECT identifier
            FROM pokemon_species
            GROUP BY identifier
            HAVING COUNT(*) > 1
        )
        """,
    )

    assert duplicates == 0


def test_custom_mapping_references_existing_pokeapi_rows(
    db: sqlite3.Connection,
) -> None:
    checks = [
        ("species_id", "pokemon_species"),
        ("pokemon_id", "pokemon"),
        ("pokemon_form_id", "pokemon_forms"),
    ]

    for column, target_table in checks:
        orphan_count = scalar(
            db,
            f"""
            SELECT COUNT(*)
            FROM custom_pokedex_fr custom
            WHERE custom."{column}" IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM "{target_table}" target
                  WHERE target.id = custom."{column}"
              )
            """,
        )

        assert orphan_count == 0, (
            f"{orphan_count} référence(s) orpheline(s) pour {column}"
        )
