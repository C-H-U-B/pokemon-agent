from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pokemon_rag.graph import nodes
from pokemon_rag.rag import grounding

graph_module = import_module("pokemon_rag.graph.graph")


def response(text):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text)
    )])


@pytest.fixture
def pipeline():
    chunk = {"document": "Contexte disponible.", "metadata": {"pokemon": "Pikachu"}}
    with (
        patch.object(nodes, "route_question", return_value={
            "route": "RAG", "intent": "DOCUMENT_SEARCH", "single_question": True,
            "pokemon": "Pikachu", "pokemon_validated": True,
        }),
        patch.object(nodes, "retrieve", return_value=[chunk]) as retrieval,
        patch.object(nodes, "retrieve_retry_context") as retry,
        patch.object(nodes.llm_client.chat.completions, "create",
                     return_value=response("Réponse provisoire.")) as generation,
        patch.object(grounding.client.chat.completions, "create",
                     return_value=response('{"decision":"PASS","reason":"OK",'
                                           '"context_sufficient":true,"unsupported_claims":[]}')) as checker,
        patch.object(graph_module, "save_trace") as save,
    ):
        yield retrieval, retry, generation, checker, save


@pytest.mark.parametrize("stage", ["retrieve_documents", "main_llm", "grounding_check", "retry_answer"])
def test_processing_failure_preserves_state_and_saves_once(pipeline, stage):
    retrieval, retry, generation, checker, save = pipeline
    failure = RuntimeError("Détail technique privé")
    if stage == "retrieve_documents":
        retrieval.side_effect = failure
    elif stage == "main_llm":
        generation.side_effect = failure
    elif stage == "grounding_check":
        checker.side_effect = failure
    else:
        checker.return_value = response('{"decision":"UNSUPPORTED","reason":"Non étayé",'
                                        '"context_sufficient":true,"unsupported_claims":["fait"]}')
        generation.side_effect = [response("Réponse provisoire."), failure]

    result = graph_module.run_graph({"question": "Question sur Pikachu"})

    assert result["execution_status"] == "ERROR"
    assert result["failed_step"] == stage
    assert result["error_type"] == "RuntimeError"
    assert result["failed_step_time"] >= 0
    assert result["route"] == "RAG"
    assert "erreur technique" in result["answer"]
    assert "Réponse provisoire" not in result["answer"]
    assert "Détail technique privé" not in result["answer"]
    assert "Détail technique privé" not in result["grounding_reason"]
    save.assert_called_once_with(result["trace"])
    assert result["trace"]["execution_status"] == "ERROR"
    assert result["trace"]["failed_step"] == stage
    attempts = [item for item in result["trace"]["attempts"] if item["step"] == stage]
    assert attempts[-1]["status"] == "ERROR"
    assert attempts[-1]["duration_seconds"] >= 0
    if "llm" in attempts[-1]:
        assert attempts[-1]["llm"]["total_tokens"] is None
    assert "router" in result["trace"]["timings"]
    retry.assert_not_called()
    if stage == "retrieve_documents":
        generation.assert_not_called()
    if stage in {"retrieve_documents", "main_llm"}:
        checker.assert_not_called()


def test_structured_returned_error_stops_before_generation(pipeline):
    _, _, generation, _, save = pipeline
    with (
        patch.object(nodes, "route_question", return_value={"route": "STRUCTURED"}),
        patch.object(nodes, "query_structured_data", return_value={
            "error": "Base indisponible", "error_type": "OperationalError",
        }),
    ):
        result = graph_module.run_graph({"question": "Évolution de Pikachu ?"})
    assert result["failed_step"] == "retrieve_structured_data"
    assert result["error_type"] == "OperationalError"
    assert result["execution_status"] == "ERROR"
    generation.assert_not_called()
    save.assert_called_once()


def test_engine_exception_preserves_last_snapshot(pipeline):
    *_, save = pipeline
    def broken_stream(*args, **kwargs):
        yield {"question": "Q", "route": "RAG", "router_time": 0.25,
               "answer": "Réponse provisoire."}
        raise RuntimeError("Moteur interrompu")

    with patch.object(graph_module.graph, "stream", side_effect=broken_stream):
        result = graph_module.run_graph({"question": "Q"})
    assert result["failed_step"] == "graph"
    assert result["trace"]["timings"]["router"] == 0.25
    assert "erreur technique" in result["answer"]
    save.assert_called_once()


def test_success_still_saves_once(pipeline):
    *_, save = pipeline
    result = graph_module.run_graph({"question": "Question sur Pikachu"})
    assert result["execution_status"] == "COMPLETED"
    assert result["answer"] == "Réponse provisoire."
    assert "failed_step" not in result["trace"]
    assert result["trace_saved"] is True
    assert result["trace_save_error"] is None
    save.assert_called_once()


@pytest.mark.parametrize("failure", [
    PermissionError("Trace inaccessible"),
    OSError("Disque plein"),
    TypeError("Trace non sérialisable"),
])
def test_trace_failure_preserves_answer_and_logs_once(pipeline, caplog, failure):
    *_, save = pipeline
    save.side_effect = failure
    result = graph_module.run_graph({"question": "Question sur Pikachu"})
    assert result["answer"] == "Réponse provisoire."
    assert result["execution_status"] == "COMPLETED"
    assert result["grounding_decision"] == "PASS"
    assert result["trace_saved"] is False
    assert result["trace_save_error"] == type(failure).__name__
    assert result["trace"]["total_time"] >= 0
    assert "started_at" not in result["trace"]
    assert "failed_step" not in result
    assert result["trace"]["trace_id"] in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is not None
    save.assert_called_once_with(result["trace"])


@pytest.mark.parametrize("stage", ["main_llm", "graph"])
def test_trace_failure_preserves_original_processing_error(pipeline, stage):
    _, _, generation, _, save = pipeline
    save.side_effect = PermissionError("Trace inaccessible")
    config = None
    if stage == "main_llm":
        generation.side_effect = RuntimeError("Génération indisponible")
        expected_error = "RuntimeError"
    else:
        config = {"recursion_limit": 2}
        expected_error = "GraphRecursionError"
    result = graph_module.run_graph({"question": "Question sur Pikachu"}, config=config)
    assert result["execution_status"] == "ERROR"
    assert result["failed_step"] == stage
    assert result["error_type"] == expected_error
    assert result["trace"]["error_type"] == expected_error
    assert result["trace_saved"] is False
    assert result["trace_save_error"] == "PermissionError"
    assert "erreur technique" in result["answer"]
    assert result["trace"]["total_time"] >= 0
    save.assert_called_once()


def test_trace_save_recovers_on_next_request(pipeline):
    *_, save = pipeline
    save.side_effect = [PermissionError("Trace inaccessible"), None]
    first = graph_module.run_graph({"question": "Première question"})
    second = graph_module.run_graph({"question": "Deuxième question"})
    assert first["trace_saved"] is False
    assert second["trace_saved"] is True
    assert second["trace_save_error"] is None
    assert second["execution_status"] == "COMPLETED"
    assert save.call_count == 2


def test_trace_save_does_not_swallow_keyboard_interrupt(pipeline):
    *_, save = pipeline
    save.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        graph_module.run_graph({"question": "Question sur Pikachu"})
    save.assert_called_once()


def test_real_graph_recursion_error_is_finalized(pipeline):
    *_, save = pipeline
    result = graph_module.run_graph(
        {"question": "Question sur Pikachu"}, config={"recursion_limit": 2},
    )
    assert result["execution_status"] == "ERROR"
    assert result["error_type"] == "GraphRecursionError"
    assert result["failed_step"] == "graph"
    assert result["route"] == "RAG"
    save.assert_called_once()


def test_next_request_succeeds_after_generation_failure(pipeline):
    _, _, generation, _, save = pipeline
    generation.side_effect = [RuntimeError("Panne"), response("Réponse correcte.")]
    failed = graph_module.run_graph({"question": "Première question"})
    succeeded = graph_module.run_graph({"question": "Deuxième question"})
    assert failed["execution_status"] == "ERROR"
    assert succeeded["execution_status"] == "COMPLETED"
    assert succeeded["answer"] == "Réponse correcte."
    assert "failed_step" not in succeeded
    assert failed["trace"]["trace_id"] != succeeded["trace"]["trace_id"]
    assert save.call_count == 2


def test_retrieval_retry_accumulates_generation_and_grounding_metrics(pipeline):
    _, retry, generation, checker, save = pipeline
    generated = response("Réponse vérifiée.")
    generated.usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    generation.return_value = generated
    retry.return_value = [{"document": "Autre contexte", "metadata": {}}]
    checks = []
    for decision in ("INSUFFICIENT", "PASS"):
        checked = response('{"decision":"' + decision + '","reason":"test",'
                           '"context_sufficient":true,"unsupported_claims":[]}')
        checked.usage = SimpleNamespace(prompt_tokens=50, completion_tokens=10, total_tokens=60)
        checks.append(checked)
    checker.side_effect = checks
    result = graph_module.run_graph({"question": "Question sur Pikachu"})
    trace = result["trace"]
    assert result["grounding_decision"] == "PASS"
    assert result["llm_total_tokens"] == trace["llm"]["total_tokens"] == 240
    assert result["grounding_total_tokens"] == trace["grounding"]["total_tokens"] == 120
    for step, timing, prefix in (("main_llm", "main_llm", "llm"),
                                  ("grounding_check", "grounding", "grounding")):
        attempts = [item for item in trace["attempts"] if item["step"] == step]
        assert [item["attempt"] for item in attempts] == [1, 2]
        duration = sum(item["duration_seconds"] for item in attempts)
        assert trace["timings"][timing] == pytest.approx(duration)
        assert trace[prefix]["tokens_per_second"] == pytest.approx(
            trace[prefix]["completion_tokens"] / duration
        )
    assert trace["steps"]["build_context"]["calls"] == 2
    save.assert_called_once()


def test_generation_retry_metrics_and_trace_analysis(pipeline, capsys):
    from pathlib import Path
    import runpy

    _, _, generation, checker, _ = pipeline
    generated = response("Réponse vérifiée.")
    generated.usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    generation.return_value = generated
    checker.side_effect = [
        response('{"decision":"UNSUPPORTED","reason":"test",'
                 '"context_sufficient":true,"unsupported_claims":["fait"]}'),
        response('{"decision":"PASS","reason":"test",'
                 '"context_sufficient":true,"unsupported_claims":[]}'),
    ]
    result = graph_module.run_graph({"question": "Question sur Pikachu"})
    trace = result["trace"]
    assert trace["llm"]["total_tokens"] == 120
    assert trace["retry_llm"]["total_tokens"] == 120
    assert trace["grounding"]["calls"] == 2
    assert trace["grounding"]["total_tokens"] is None
    assert trace["grounding"]["unknown_usage_calls"] == 2
    analyzer = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                  "scripts/observability/analyze_traces.py"))
    legacy = {"grounding": {"prompt_tokens": 10, "completion_tokens": 5,
                            "total_tokens": 15, "tokens_per_second": 2.0}}
    analyzer["print_llm_summary"]("Grounding", [trace, legacy], "grounding")
    output = capsys.readouterr().out
    assert "traces mesurées      : 1/2" in output
    assert "usage incomplet      : 1/2" in output
