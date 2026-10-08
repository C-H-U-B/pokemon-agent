"""Compteurs de tests des deux README, comparés à la collecte pytest. Aucun test n'est exécuté.

    python scripts/check_test_counts.py           échoue si un compteur est périmé
    python scripts/check_test_counts.py --write   met les deux README à jour
    python scripts/check_test_counts.py --ci      ne vérifie que le compteur de l'intégration continue
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Tous les tests, ceux sans modèle, ceux de l'intégration continue (même sélection que le workflow).
SELECTIONS = (None, "not llm and not models", "not real_data and not llm and not models")
# Une expression par compteur, dans l'ordre de SELECTIONS ; le groupe 2 est le nombre affiché.
PATTERNS = {
    "README_FR.md": (r"(\| Tests \| )([\d ]+)( tests, dont )", r"( tests, dont )([\d ]+)( sans aucun modèle)",
                     r"(statique et les )([\d ]+)( tests )"),
    "README.md": (r"(\| Tests \| )([\d,]+)( tests, )", r"( tests, )([\d,]+)( of which need no model)",
                  r"(checks and the )([\d,]+)( tests )"),
}
THOUSANDS = {"README_FR.md": " ", "README.md": ","}


def collected(selection: str | None) -> int:
    command = [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"]
    if selection:
        command += ["-m", selection]
    output = subprocess.run(command, cwd=ROOT, capture_output=True, text=True).stdout
    match = re.search(r"(\d+)(?:/\d+)? tests collected", output)
    if not match:
        sys.exit(f"Collecte pytest illisible :\n{output[-800:]}")
    return int(match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="Met les README à jour au lieu d'échouer.")
    parser.add_argument("--ci", action="store_true", help="Ne vérifie que le compteur de l'intégration continue.")
    args = parser.parse_args()

    # ponytail: une collecte par sélection (environ 15 s chacune) ; une seule collecte lisant les
    # marqueurs suffirait si ce contrôle devenait trop lent.
    indices = [2] if args.ci else [0, 1, 2]
    counts = {index: collected(SELECTIONS[index]) for index in indices}
    stale = []
    for name, patterns in PATTERNS.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        for index in indices:
            match = re.search(patterns[index], text)
            if not match:
                sys.exit(f"{name} : compteur {index + 1} introuvable, adapter PATTERNS à la nouvelle phrase.")
            shown = int(re.sub(r"\D", "", match.group(2)))
            if shown != counts[index]:
                stale.append(f"{name} : {shown} affiché, {counts[index]} collectés ({SELECTIONS[index] or 'tous'})")
                text = text[:match.start(2)] + f"{counts[index]:,}".replace(",", THOUSANDS[name]) + text[match.end(2):]
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
    print("Tests collectés :", ", ".join(str(counts[index]) for index in indices))
    if stale:
        print("\n".join(stale))
        if not args.write:
            sys.exit("Compteurs périmés : relancer avec --write.")
        print("README mis à jour.")
    else:
        print("Compteurs des README à jour.")


if __name__ == "__main__":
    main()
