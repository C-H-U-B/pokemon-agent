"""Score une relecture humaine ; les cases non relues restent hors des scores."""
import argparse
import json
from pathlib import Path


def matches_reference(actual, expected):
    """Champs sélectionnés exacts ; listes complètes, sans dépendre de leur ordre."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches_reference(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        # Recherche d'une correspondance bijective, y compris pour les doublons.
        if not expected:
            return True
        return any(matches_reference(item, expected[0]) and
                   matches_reference(actual[:i] + actual[i+1:], expected[1:])
                   for i, item in enumerate(actual))
    return type(actual) is type(expected) and actual == expected


def summarize(cases):
    fields = ("factually_correct", "complete", "unsupported_claims", "abstained", "abstention_appropriate")
    reviewed = []
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Identifiants de cas dupliqués")
    for case in cases:
        review = case["review"]
        if all(review.get(key) is None for key in fields):
            continue
        if not review.get("reviewer", "").strip() or not all(type(review.get(key)) is bool for key in fields):
            raise ValueError(f"Relecture incomplète : {case['id']}")
        reviewed.append(review)
    answered = [r for r in reviewed if not r["abstained"]]
    abstained = [r for r in reviewed if r["abstained"]]
    structured = [case for case in cases if "structured" in case["reference"]]
    return {
        "total": len(cases), "reviewed": len(reviewed), "pending": len(cases) - len(reviewed),
        "answered": len(answered),
        "factually_correct": sum(r["factually_correct"] for r in answered),
        "complete": sum(r["complete"] for r in answered),
        "with_unsupported_claims": sum(r["unsupported_claims"] for r in answered),
        "abstained": len(abstained),
        "appropriate_abstentions": sum(r["abstention_appropriate"] for r in abstained),
        "structured_checked": len(structured),
        "structured_correct": sum(matches_reference(c.get("structured_result"), c["reference"]["structured"])
                                  for c in structured),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.report.read_text(encoding="utf-8"))["cases"]), indent=2))


if __name__ == "__main__":
    main()
