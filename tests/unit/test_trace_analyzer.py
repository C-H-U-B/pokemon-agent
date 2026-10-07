"""L'analyseur des traces du graphe refuse un autre format au lieu d'afficher des temps nuls."""
import json
import runpy
from pathlib import Path

import pytest

load_traces = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/observability/analyze_traces.py"))["load_traces"]


def test_web_traces_are_refused_instead_of_summarised_as_zero_seconds(tmp_path):
    path = tmp_path / "web_traces.jsonl"
    path.write_text(json.dumps({"question": "q", "outcome": "answered", "seconds": {"total": 12.0}, "tools": []}) + "\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="web_traces"):
        load_traces(path)


def test_graph_traces_are_loaded(tmp_path):
    path = tmp_path / "graph_traces.jsonl"
    path.write_text(json.dumps({"question": "q", "total_time": 1.5, "timings": {}}) + "\n", encoding="utf-8")
    assert load_traces(path)[0]["total_time"] == 1.5
