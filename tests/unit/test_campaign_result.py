"""Le résultat cité par les README ne retient que les runs complets du modèle de référence, le dernier jour."""
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "campaign_result", Path(__file__).resolve().parents[2] / "scripts" / "campaign_result.py")
campaign_result = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(campaign_result)


def _run(run_id, outcomes, model="qwen/qwen3-vl-8b"):
    return [json.dumps({"run_id": run_id, "model": model, "case_id": f"c{i}", "passed": ok})
            for i, ok in enumerate(outcomes)]


def test_latest_day_complete_runs_only():
    lines = (
        _run("2026-10-12T10:00:00+02:00", [True, True, True])  # jour précédent : écarté
        + _run("2026-10-13T11:00:00+02:00", [True, False, False], model="gemma12b")  # autre modèle
        + _run("2026-10-13T12:00:00+02:00", [True, True, False])
        + _run("2026-10-13T12:30:00+02:00", [False])  # run partiel (-k)
        + _run("2026-10-13T13:00:00+02:00", [True, True, True])
    )
    size, day, scores = campaign_result.latest_runs(lines)
    assert (size, day, scores) == (3, "2026-10-13", [2, 3])
    texts = campaign_result.sentences(size, day, scores)
    assert texts["README_FR.md"].startswith("2 à 3 questions sur 3 réussies avec Qwen3-VL 8B en local, sur 2 exécutions le 13 octobre 2026")
    assert texts["README.md"].startswith("2 to 3 of 3 questions passed with Qwen3-VL 8B running locally, over 2 runs on 13 October 2026")
