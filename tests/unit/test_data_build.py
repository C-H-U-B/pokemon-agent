"""Garanties des constructeurs de données, sans la vraie base, sans index ni modèle."""
from __future__ import annotations

import hashlib
import runpy
import sqlite3
from pathlib import Path

import pytest

from pokemon_rag.rag import retrieval

builder = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/pokeapi/build_pokeapi_db.py"))
replacing, record_sources, orphans = builder["replacing"], builder["record_sources"], builder["orphans"]


def test_failed_build_leaves_previous_database_untouched(tmp_path):
    target = tmp_path / "pokemon.db"
    target.write_text("ancienne base")

    with pytest.raises(RuntimeError):
        with replacing(target) as building:
            building.write_text("base partielle")
            raise RuntimeError("validation refusée")

    assert target.read_text() == "ancienne base"


def test_successful_build_replaces_database_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "pokemon.db"
    target.write_text("ancienne base")

    with replacing(target) as building:
        assert building != target
        building.write_text("nouvelle base")

    assert target.read_text() == "nouvelle base"
    assert list(tmp_path.iterdir()) == [target]


def test_interrupted_build_does_not_leak_into_the_next_one(tmp_path):
    target = tmp_path / "pokemon.db"
    (tmp_path / "pokemon.db.tmp").write_text("reste d'un build interrompu")

    with replacing(target) as building:
        assert not building.exists()
        building.write_text("nouvelle base")

    assert target.read_text() == "nouvelle base"


def test_build_info_records_fingerprint_size_and_origin_of_each_source(tmp_path):
    known, unknown = tmp_path / "moves.csv", tmp_path / "types.csv"
    known.write_bytes(b"id\n1\n")
    unknown.write_bytes(b"id\n")
    conn = sqlite3.connect(":memory:")

    record_sources(conn, [(known, "abc123"), (unknown, None)])
    # Second appel, comme le constructeur de pokemon.db qui ajoute le tableur aux lignes des CSV.
    record_sources(conn, [(known, None)])

    rows = conn.execute("SELECT name, sha256, bytes, origin FROM build_info ORDER BY rowid").fetchall()
    assert rows == [
        ("moves.csv", hashlib.sha256(b"id\n1\n").hexdigest(), 5, "abc123"),
        ("types.csv", hashlib.sha256(b"id\n").hexdigest(), 3, None),
        ("moves.csv", hashlib.sha256(b"id\n1\n").hexdigest(), 5, None),
    ]
    assert conn.execute("SELECT COUNT(*) FROM build_info WHERE built_at IS NULL").fetchone()[0] == 0


def test_orphans_names_only_the_broken_reference_and_ignores_empty_values():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE moves (id INTEGER);
        CREATE TABLE pokemon (id INTEGER);
        CREATE TABLE pokemon_moves (pokemon_id INTEGER, move_id INTEGER);
        INSERT INTO moves VALUES (1);
        INSERT INTO pokemon VALUES (10);
        INSERT INTO pokemon_moves VALUES (10, 1), (10, NULL), (10, 99), (10, 98);
        """
    )

    broken = orphans(conn, [
        ("pokemon_moves", "pokemon_id", "pokemon", "id"),
        ("pokemon_moves", "move_id", "moves", "id"),
    ])

    assert broken == ["pokemon_moves.move_id -> moves.id : 2"]


def test_index_built_with_another_embedding_model_is_refused():
    with pytest.raises(RuntimeError, match="autre-modele"):
        retrieval.check_index_model({"hnsw:space": "cosine", "embedding_model": "autre-modele"})


@pytest.mark.parametrize("metadata", [None, {"hnsw:space": "cosine"}, {"embedding_model": retrieval.EMBEDDING_MODEL}],
                         ids=["no-metadata", "release-without-note", "same-model"])
def test_index_without_note_or_with_the_same_model_is_accepted(metadata):
    retrieval.check_index_model(metadata)
