import pytest

from pokemon_rag.observability.metrics import aggregate_attempts, record_attempt
from pokemon_rag.observability.tracing import create_trace, format_trace


def measured(completion):
    return {
        "llm_usage_known": True, "llm_prompt_tokens": 100,
        "llm_completion_tokens": completion, "llm_total_tokens": 100 + completion,
    }


def test_attempts_accumulate_and_throughput_is_weighted():
    first = record_attempt("main_llm", {}, measured(10), 2.0)
    attempts = record_attempt("main_llm", {"attempts": first}, measured(30), 4.0)
    assert len(first) == 1
    assert [item["attempt"] for item in attempts] == [1, 2]
    timings, steps, llms = aggregate_attempts(attempts)
    assert timings["main_llm"] == 6.0
    assert steps["main_llm"] == {"calls": 2, "errors": 0, "duration_seconds": 6.0}
    assert llms["llm"]["total_tokens"] == 240
    assert llms["llm"]["tokens_per_second"] == pytest.approx(40 / 6)


def test_failed_attempt_keeps_known_subtotal_but_total_is_unknown():
    attempts = record_attempt("main_llm", {}, measured(10), 2.0)
    attempts = record_attempt("main_llm", {"attempts": attempts}, {
        "execution_status": "ERROR", "error_type": "TimeoutError",
    }, 3.0)
    timings, steps, llms = aggregate_attempts(attempts)
    assert timings["main_llm"] == 5.0
    assert steps["main_llm"]["errors"] == 1
    assert llms["llm"]["known_tokens"]["total_tokens"] == 110
    assert llms["llm"]["total_tokens"] is None
    assert llms["llm"]["tokens_per_second"] is None
    assert llms["llm"]["unknown_usage_calls"] == 1
    trace = create_trace("Q")
    trace.update(llms)
    assert "inconnu" in format_trace(trace)


def test_empty_context_does_not_count_as_llm_call():
    attempts = record_attempt("main_llm", {}, {"llm_called": False}, 0.01)
    _, _, llms = aggregate_attempts(attempts)
    assert llms == {}


def test_context_builders_share_cumulative_timing():
    first = record_attempt("build_context", {}, {"context_time": 0.1}, 0.2)
    attempts = record_attempt("build_hybrid_context", {"attempts": first}, {"context_time": 0.3}, 0.4)
    timings, _, _ = aggregate_attempts(attempts)
    assert timings["context"] == pytest.approx(0.6)
