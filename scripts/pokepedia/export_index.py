"""Exporte la seule collection Poképédia vers un index neuf et son archive, prêts à publier.

L'index local peut contenir d'autres collections et les restes d'anciennes ingestions : ils ne
doivent pas partir dans une release. Les vecteurs sont recopiés tels quels, aucun modèle n'est
chargé, et l'index d'origine n'est que lu.

    python scripts/pokepedia/export_index.py     # dist/chroma_db/ et dist/chroma_db.tar.gz
"""
from __future__ import annotations

import argparse
import hashlib
import tarfile
import tempfile
from pathlib import Path

import chromadb
from tqdm import tqdm

from pokemon_rag.config import CHROMA_PATH, PROJECT_ROOT

COLLECTION_NAME = "pokemon_documents"
# Lots de 500 : un get() plus large dépasse la limite de variables SQL de Chroma/SQLite.
BATCH_SIZE = 500


def export(output: Path) -> int:
    """Recopie identifiants, textes, métadonnées et vecteurs ; retourne le nombre de fragments."""
    source = chromadb.PersistentClient(path=str(CHROMA_PATH)).get_collection(COLLECTION_NAME)
    target = chromadb.PersistentClient(path=str(output)).create_collection(
        COLLECTION_NAME, metadata=source.metadata)
    total = source.count()
    with tqdm(total=total, desc="Export", unit="fragment", dynamic_ncols=True) as progress:
        for offset in range(0, total, BATCH_SIZE):
            batch = source.get(include=["documents", "metadatas", "embeddings"],
                               limit=BATCH_SIZE, offset=offset)
            target.add(ids=batch["ids"], documents=batch["documents"],
                       metadatas=batch["metadatas"], embeddings=batch["embeddings"])
            progress.update(len(batch["ids"]))
    if target.count() != total:
        raise SystemExit(f"Export incomplet : {target.count()} fragments sur {total}.")
    return total


def check_archive(archive: Path, total: int) -> None:
    """Rouvre l'archive comme le fera un utilisateur : une seule collection, complète et interrogeable."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(folder, filter="data")
        client = chromadb.PersistentClient(path=str(Path(folder) / "chroma_db"))
        names = [collection.name for collection in client.list_collections()]
        if names != [COLLECTION_NAME]:
            raise SystemExit(f"Collections inattendues dans l'archive : {names}")
        collection = client.get_collection(COLLECTION_NAME)
        if collection.count() != total:
            raise SystemExit(f"Archive incomplète : {collection.count()} fragments sur {total}.")
        # Un fragment doit se retrouver lui-même en tête d'une recherche par son propre vecteur.
        sample = collection.get(limit=1, include=["embeddings"])
        nearest = collection.query(query_embeddings=[sample["embeddings"][0]], n_results=1)["ids"][0][0]
        if nearest != sample["ids"][0]:
            raise SystemExit("Index vectoriel incohérent dans l'archive.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist" / "chroma_db",
                        help="Dossier du nouvel index ; doit être absent.")
    output = parser.parse_args().output
    archive = output.parent / "chroma_db.tar.gz"
    if output.exists() or archive.exists():
        raise SystemExit(f"{output} ou {archive} existe déjà : les supprimer avant de relancer.")
    output.parent.mkdir(parents=True, exist_ok=True)

    total = export(output)
    print("Création de l'archive...")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(output, arcname="chroma_db")
    print("Vérification de l'archive...")
    check_archive(archive, total)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(f"Fragments : {total:,}")
    print(f"Archive   : {archive} ({archive.stat().st_size / 1e6:.0f} Mo)")
    print(f"SHA-256   : {digest}")


if __name__ == "__main__":
    main()
