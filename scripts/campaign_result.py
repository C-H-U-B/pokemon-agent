"""Résultat de la campagne structurée cité par les deux README, recalculé depuis test_results/. Aucun modèle n'est appelé.

    python scripts/campaign_result.py           affiche le résultat, échoue si un README est périmé
    python scripts/campaign_result.py --write   met les deux README à jour

Les résultats sont locaux (test_results/ est ignoré par Git) : ce contrôle ne tourne pas en CI.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test_results" / "adk_structured_database_e2e.jsonl"
REFERENCE_MODEL = "qwen/qwen3-vl-8b"
LABEL = "Qwen3-VL 8B"
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre")
# Ligne « En bref » de chaque README ; le groupe 2 est la phrase remplacée.
ROWS = {
    "README_FR.md": r"(\| Campagne de bout en bout \| )(.*)( \|)",
    "README.md": r"(\| End-to-end campaign \| )(.*)( \|)",
}


def latest_runs(lines, model: str = REFERENCE_MODEL) -> tuple[int, str, list[int]]:
    """Taille de la campagne, dernier jour où elle a tourné en entier, réussites de chaque run complet ce jour-là.

    Un run est complet s'il compte autant de cas que le plus grand run du modèle ; les runs partiels
    (`-k`) et les autres modèles sont ignorés.
    """
    # ponytail: « même jour » tient lieu de « même code », car un run ne note pas son commit ; un
    # correctif mesuré le jour même mêle l'avant et l'après (affiché en fourchette). Noter le commit
    # dans chaque run pour s'en passer. Retirer des cas laisserait aussi l'ancien maximum l'emporter.
    runs: dict[str, list[int]] = {}
    for line in lines:
        record = json.loads(line)
        if record.get("model") != model:
            continue
        run = runs.setdefault(record["run_id"], [0, 0])
        run[0] += 1
        run[1] += bool(record["passed"])
    if not runs:
        raise ValueError(f"aucun run de {model}")
    size = max(total for total, _ in runs.values())
    complete = {run_id: passed for run_id, (total, passed) in runs.items() if total == size}
    day = max(run_id[:10] for run_id in complete)
    return size, day, [passed for run_id, passed in complete.items() if run_id.startswith(day)]


def sentences(size: int, day: str, scores: list[int]) -> dict[str, str]:
    low, high = min(scores), max(scores)
    runs, when = len(scores), date.fromisoformat(day)
    plural = "s" if runs > 1 else ""
    fr_score = str(high) if low == high else f"{low} à {high}"
    en_score = str(high) if low == high else f"{low} to {high}"
    return {
        "README_FR.md": f"{fr_score} questions sur {size} réussies avec {LABEL} en local, sur {runs} exécution{plural}"
                        f" le {when.day} {MONTHS[when.month - 1]} {when.year} (campagne structurée)",
        "README.md": f"{en_score} of {size} questions passed with {LABEL} running locally, over {runs} run{plural}"
                     f" on {when.day} {when:%B} {when.year} (structured campaign)",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="Met les README à jour au lieu d'échouer.")
    args = parser.parse_args()
    if not RESULTS.exists():
        sys.exit(f"{RESULTS} absent : lancer d'abord la campagne structurée.")
    size, day, scores = latest_runs(RESULTS.read_text(encoding="utf-8").splitlines())
    expected = sentences(size, day, scores)
    print(expected["README_FR.md"])
    stale = []
    for name, pattern in ROWS.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        match = re.search(pattern, text)
        if not match:
            sys.exit(f"{name} : ligne de campagne introuvable, adapter ROWS.")
        if match.group(2) != expected[name]:
            stale.append(name)
            if args.write:
                path.write_text(text[:match.start(2)] + expected[name] + text[match.end(2):], encoding="utf-8",
                                newline="\n")
    if stale and not args.write:
        sys.exit(f"Résultat périmé dans {', '.join(stale)} : relancer avec --write.")
    print("README mis à jour." if stale else "Résultat des README à jour.")


if __name__ == "__main__":
    main()
