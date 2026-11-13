"""Lecture d'une trajectoire OpenClaw par le benchmark : appels, défauts de schéma, réponse finale. Aucun OpenClaw ni LLM."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "benchmark_openclaw_vs_adk", Path(__file__).parents[2] / "benchmarks/benchmark_openclaw_vs_adk.py")
bench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench)


def event(type_, data, source="transcript"):
    return {"source": source, "type": type_, "data": data}


def test_trajectory_keeps_transcript_calls_with_defaults_and_last_text_answer():
    events = [
        event("assistant.message", {"message": {"content": [{"type": "toolCall", "name": "pokemon__pokemon_moves"}]}}),
        event("tool.call", {"name": "pokemon__pokemon_moves", "arguments": {"pokemon": "Nigirigon", "limit": 100}}),
        # Le même appel vu par le runtime ne doit pas être compté deux fois.
        event("tool.call", {"name": "pokemon__pokemon_moves", "arguments": {"pokemon": "Nigirigon"}}, "runtime"),
        event("assistant.message", {"message": {"content": [{"type": "text", "text": "Ocroupi"}]}}),
    ]
    calls, answer = bench.trajectory_calls(events, {"pokemon_moves": {"limit": 30, "damage_class": None}})
    assert calls == [{"name": "pokemon_moves", "args": {"limit": 100, "damage_class": None, "pokemon": "Nigirigon"}}]
    assert answer == "Ocroupi"


def test_trajectory_without_answer_is_empty_so_the_benchmark_stops():
    assert bench.trajectory_calls([event("session.started", {}, "runtime")], {}) == ([], "")
