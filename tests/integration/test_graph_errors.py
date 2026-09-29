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
    save.assert_called_once()


def test_trace_failure_is_not_retried_as_processing_failure(pipeline):
    *_, save = pipeline
    save.side_effect = PermissionError("Trace inaccessible")
    with pytest.raises(graph_module.TraceFinalizationError):
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
