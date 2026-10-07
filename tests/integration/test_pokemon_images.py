"""Illustration de chaque entrée du catalogue : adresse construite depuis les identifiants de la base.

Risque : une forme recevrait l'image de son espèce (Raichu d'Alola montrerait Raichu) ou une adresse
qui n'existe pas. La présence réelle des images sur le dépôt PokeAPI/sprites a été vérifiée une fois
par requêtes réseau (1 270 entrées sur 1 275) ; ce test ne fait aucune requête.
"""
import sqlite3
from contextlib import closing

import pytest

from pokemon_rag.config import DB_PATH
from pokemon_rag.constraints.query_constraints import normalize
from pokemon_rag.structured.query_engine import ARTWORK_URL, pokemon_image_urls

pytestmark = pytest.mark.real_data


@pytest.mark.parametrize("name,key", [
    ("Pikachu", "25"),
    ("Raichu d’Alola", "10100"),          # forme régionale : son propre pokemon_id
    ("Méga-Dracaufeu X", "10034"),
    ("Motisma Lavage", "10009"),
    ("Arceus", "493"),                    # nom d'espèce de la forme par défaut « Arceus Normal »
    ("Arceus Insecte", "493-bug"),        # forme cosmétique : espèce-forme
    ("Xerneas Déchaîné", "716-active"),
])
def test_each_form_gets_its_own_artwork(name, key):
    assert pokemon_image_urls()[normalize(name)] == ARTWORK_URL.format(key)


def test_every_linked_entry_of_the_spreadsheet_has_an_image():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        names = [row[0] for row in conn.execute("SELECT name_fr FROM custom_pokedex WHERE pokemon_id IS NOT NULL")]
    urls = pokemon_image_urls()
    assert len(names) == 1270
    assert [name for name in names if normalize(name) not in urls] == []
