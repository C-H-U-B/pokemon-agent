"""Petit catalogue déterministe : aucun accès à pokemon.db."""
import sqlite3
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def isolated_name_catalog(request, monkeypatch):
    if request.module.__name__.split(".")[-1] not in {"test_router", "test_query_parser"}:
        return
    from pokemon_rag.graph import router
    from pokemon_rag.structured import query_engine

    connect = sqlite3.connect
    def catalog(*args, **kwargs):
        conn = connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE custom_pokedex(name_fr TEXT, name_en TEXT);
            CREATE TABLE language_ids(fr INTEGER, en INTEGER);
            INSERT INTO language_ids VALUES (5, 9);
            CREATE TABLE pokemon_species(id INTEGER, identifier TEXT);
            CREATE TABLE pokemon_species_names(pokemon_species_id INTEGER, local_language_id INTEGER, name TEXT);
            CREATE TABLE moves(id INTEGER, identifier TEXT);
            CREATE TABLE move_names(move_id INTEGER, local_language_id INTEGER, name TEXT);
            CREATE TABLE version_groups(identifier TEXT);
            INSERT INTO version_groups VALUES ('red-blue'), ('sun-moon'), ('sword-shield'), ('scarlet-violet');
            INSERT INTO moves VALUES (344, 'volt-tackle');
            INSERT INTO move_names VALUES (344, 5, 'Électacle'), (344, 9, 'Volt Tackle');
        ''')
        names = [('Pikachu', 'Pikachu'), ('Raichu', 'Raichu'), ('Dracaufeu', 'Charizard'),
                 ('Roitiflam', 'Emboar'), ('Tutafeh', 'Yamask'), ('Rattata', 'Rattata'),
                 ('Caratroc', 'Shuckle'), ('Lovdisc', 'Luvdisc')]
        for identifier, (fr, en) in enumerate(names, 1):
            conn.execute('INSERT INTO custom_pokedex VALUES (?, ?)', (fr, en))
            conn.execute('INSERT INTO pokemon_species VALUES (?, ?)', (identifier, en.lower()))
            conn.executemany('INSERT INTO pokemon_species_names VALUES (?, ?, ?)',
                             [(identifier, 5, fr), (identifier, 9, en)])
        conn.execute("INSERT INTO custom_pokedex VALUES ('Tutafeh de Galar', 'Galarian Yamask')")
        return conn

    monkeypatch.setattr(router, "sqlite3", SimpleNamespace(connect=catalog, Row=sqlite3.Row))
    monkeypatch.setattr(query_engine, "_connect", catalog)

