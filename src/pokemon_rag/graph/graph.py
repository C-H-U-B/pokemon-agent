from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

from pokemon_rag.graph.nodes import (
    build_context,
    build_hybrid_context,
    call_main_llm,
    format_structured_answer,
    grounding_check,
    reject_multi_question,
    retrieve_documents,
    retrieve_structured_data,
    retry_answer,
    retry_retrieval,
    route_query,
)

from pokemon_rag.observability.tracing import (
    create_trace,
    finalize_trace,
    save_trace,
    set_llm_metrics,
    set_retrieval_metrics,
    set_retry_counts,
    set_timing,
    set_trace_value,
)


class PokemonState(TypedDict, total=False):
    question: str
    verbose: bool
    route: str
    intent: str
    router_mode: str | None
    information_need: str
    pokemon: str | None
    pokemon_validated: bool
    single_question: bool
    router_reason: str
    router_time: float
    retrieved_documents: list[dict]
    context_documents: list[dict]
    structured_result: dict
    structured_context: str
    rag_context: str
    answer: str
    retrieval_time: float
    retry_retrieval_time: float
    structured_time: float
    structured_parse_time: float
    structured_execution_time: float
    structured_format_time: float
    context_time: float
    llm_time: float
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_tokens_per_second: float
    grounding_decision: str
    grounding_reason: str
    grounding_time: float
    grounding_prompt_tokens: int
    grounding_completion_tokens: int
    grounding_total_tokens: int
    grounding_tokens_per_second: float
    retrieval_retry_count: int
    generation_retry_count: int
    retry_llm_time: float
    retry_llm_prompt_tokens: int
    retry_llm_completion_tokens: int
    retry_llm_total_tokens: int
    retry_llm_tokens_per_second: float
    trace: dict[str, Any]
    trace_saved: bool
    trace_save_error: str | None
    execution_status: str
    failed_step: str
    error_type: str
    failed_step_time: float


def initialize_trace(state: PokemonState) -> dict:
    """Crée une trace au début de chaque exécution du graphe."""
    return {"trace": create_trace(state["question"]), "execution_status": "RUNNING"}


def finalize_observability(state: PokemonState) -> dict:
    """Finalise la trace ; un échec de persistance ne bloque pas la réponse."""
    trace = state.get("trace")
    if trace is None:
        trace = create_trace(state["question"])

    status = "ERROR" if state.get("execution_status") == "ERROR" else "COMPLETED"
    set_trace_value(trace, "execution_status", status)
    for key in ("failed_step", "error_type", "failed_step_time"):
        if key in state:
            set_trace_value(trace, key, state[key])

    set_trace_value(trace, "route", state.get("route"))
    set_trace_value(trace, "intent", state.get("intent"))
    set_trace_value(trace, "router_mode", state.get("router_mode"))
    set_trace_value(trace, "pokemon", state.get("pokemon"))
    set_trace_value(trace, "single_question", state.get("single_question"))
    set_trace_value(
        trace,
        "grounding_decision",
        state.get("grounding_decision"),
    )

    timing_fields = {
        "router": "router_time",
        "retrieval": "retrieval_time",
        "retry_retrieval": "retry_retrieval_time",
        "structured": "structured_time",
        "structured_parse": "structured_parse_time",
        "structured_execution": "structured_execution_time",
        "structured_format": "structured_format_time",
        "context": "context_time",
        "main_llm": "llm_time",
        "grounding": "grounding_time",
        "retry_llm": "retry_llm_time",
    }
    for trace_name, state_name in timing_fields.items():
        value = state.get(state_name)
        if value is not None:
            set_timing(trace, trace_name, value)

    retrieved_documents = state.get("retrieved_documents") or []
    context_documents = state.get("context_documents") or []
    context = state.get("rag_context") or ""

    set_retrieval_metrics(
        trace,
        retrieved_chunks=len(retrieved_documents),
        context_chunks=len(context_documents),
        context_chars=len(context),
    )
    set_retry_counts(
        trace,
        retrieval=state.get("retrieval_retry_count", 0),
        generation=state.get("generation_retry_count", 0),
    )

    if state.get("llm_time") is not None:
        set_llm_metrics(
            trace,
            "llm",
            prompt_tokens=state.get("llm_prompt_tokens", 0),
            completion_tokens=state.get("llm_completion_tokens", 0),
            total_tokens=state.get("llm_total_tokens", 0),
            tokens_per_second=state.get("llm_tokens_per_second", 0.0),
        )

    if state.get("grounding_time") is not None:
        set_llm_metrics(
            trace,
            "grounding",
            prompt_tokens=state.get("grounding_prompt_tokens", 0),
            completion_tokens=state.get("grounding_completion_tokens", 0),
            total_tokens=state.get("grounding_total_tokens", 0),
            tokens_per_second=state.get("grounding_tokens_per_second", 0.0),
        )

    if state.get("retry_llm_time") is not None:
        set_llm_metrics(
            trace,
            "retry_llm",
            prompt_tokens=state.get("retry_llm_prompt_tokens", 0),
            completion_tokens=state.get("retry_llm_completion_tokens", 0),
            total_tokens=state.get("retry_llm_total_tokens", 0),
            tokens_per_second=state.get("retry_llm_tokens_per_second", 0.0),
        )

    finalize_trace(trace)
    trace_saved = False
    trace_save_error = None
    try:
        save_trace(trace)
        trace_saved = True
    except Exception as exc:
        # Frontière de persistance uniquement : erreurs d'I/O ou de sérialisation.
        # Pas de reprise automatique, car une écriture partielle est possible.
        trace_save_error = type(exc).__name__
        logger.exception("Impossible de sauvegarder la trace %s", trace["trace_id"])

    return {
        "trace": trace,
        "execution_status": status,
        "trace_saved": trace_saved,
        "trace_save_error": trace_save_error,
    }


def processing_error(state: PokemonState) -> dict:
    """Ne restitue jamais une réponse partielle après une panne technique."""
    return {
        "answer": (
            "Une erreur technique m'empêche de terminer cette recherche. "
            "Merci de réessayer plus tard."
        ),
        "execution_status": "ERROR",
        "grounding_decision": "ERROR",
        "grounding_reason": "Le traitement a été interrompu par une erreur technique.",
    }


def protect_node(name: str, node: Callable) -> Callable:
    """Conserve l'état acquis et transforme une exception en transition d'erreur."""
    def protected(state: PokemonState) -> dict:
        start = time.perf_counter()
        try:
            result = node(state)
            structured = result.get("structured_result") or {}
            if structured.get("error"):
                result.update({
                    "execution_status": "ERROR",
                    "failed_step": name,
                    "error_type": structured.get("error_type") or "StructuredQueryError",
                    "failed_step_time": time.perf_counter() - start,
                })
            return result
        except Exception as exc:
            logger.exception("Échec de l'étape %s", name)
            return {
                "execution_status": "ERROR",
                "failed_step": name,
                "error_type": type(exc).__name__,
                "failed_step_time": time.perf_counter() - start,
            }
    return protected


def route_or_error(selector: Callable) -> Callable:
    def select(state: PokemonState) -> str:
        if state.get("execution_status") == "ERROR":
            return "error"
        return selector(state)
    return select


class TraceFinalizationError(RuntimeError):
    """Erreur de finalisation distincte d'une panne de traitement."""


def finalize_node(state: PokemonState) -> dict:
    try:
        return finalize_observability(state)
    except Exception as exc:
        # Ne pas relancer une sauvegarde qui a pu écrire avant d'échouer.
        raise TraceFinalizationError("Échec de la finalisation de la trace") from exc


def route_after_router(state: PokemonState) -> str:
    if not state.get("single_question", True):
        return "reject"
    return state.get("route", "RAG").lower()


def route_after_structured(state: PokemonState) -> str:
    return "documents" if state.get("route") == "HYBRID" else "fast_path"


def route_after_documents(state: PokemonState) -> str:
    return "hybrid" if state.get("route") == "HYBRID" else "rag"


def route_after_retry_retrieval(state: PokemonState) -> str:
    return "hybrid" if state.get("route") == "HYBRID" else "rag"


def route_after_grounding(state: PokemonState) -> str:
    decision = state.get("grounding_decision")

    if decision == "PASS":
        return "pass"

    if decision == "INSUFFICIENT":
        if state.get("retrieval_retry_count", 0) < 1:
            return "retry_retrieval"
        return "fail"

    if decision in {"UNSUPPORTED", "CONTRADICTION", "INCOMPLETE"}:
        if state.get("generation_retry_count", 0) < 1:
            return "retry_answer"
        return "fail"

    return "fail"


def abstain_after_grounding_failure(state: PokemonState) -> dict:
    """Remplace la réponse rejetée tout en conservant le diagnostic du contrôle."""
    return {
        "answer": (
            "Je ne peux pas fournir de réponse suffisamment fiable à partir "
            "des sources disponibles. Je préfère m'abstenir plutôt que de "
            "présenter une réponse non validée."
        ),
    }


def mark_generation_retry(state: PokemonState) -> dict:
    return {
        "generation_retry_count": state.get("generation_retry_count", 0) + 1
    }


builder = StateGraph(PokemonState)

for name, node in {
    "initialize_trace": initialize_trace,
    "router": route_query,
    "reject_multi_question": reject_multi_question,
    "retrieve_documents": retrieve_documents,
    "retrieve_structured_data": retrieve_structured_data,
    "build_context": build_context,
    "build_hybrid_context": build_hybrid_context,
    "format_structured_answer": format_structured_answer,
    "main_llm": call_main_llm,
    "grounding_check": grounding_check,
    "mark_generation_retry": mark_generation_retry,
    "retry_answer": retry_answer,
    "retry_retrieval": retry_retrieval,
    "abstain": abstain_after_grounding_failure,
}.items():
    builder.add_node(name, protect_node(name, node))
builder.add_node("processing_error", processing_error)
builder.add_node("finalize_observability", finalize_node)


def add_next(source: str, target: str) -> None:
    builder.add_conditional_edges(
        source,
        route_or_error(lambda state: "next"),
        {"next": target, "error": "processing_error"},
    )

builder.add_edge(START, "initialize_trace")
add_next("initialize_trace", "router")
builder.add_conditional_edges(
    "router",
    route_or_error(route_after_router),
    {
        "error": "processing_error",
        "reject": "reject_multi_question",
        "rag": "retrieve_documents",
        "structured": "retrieve_structured_data",
        "hybrid": "retrieve_structured_data",
    },
)
add_next("reject_multi_question", "finalize_observability")

builder.add_conditional_edges(
    "retrieve_structured_data",
    route_or_error(route_after_structured),
    {
        "error": "processing_error",
        "documents": "retrieve_documents",
        "fast_path": "format_structured_answer",
    },
)
add_next("format_structured_answer", "finalize_observability")

builder.add_conditional_edges(
    "retrieve_documents",
    route_or_error(route_after_documents),
    {
        "error": "processing_error",
        "rag": "build_context",
        "hybrid": "build_hybrid_context",
    },
)

add_next("build_context", "main_llm")
add_next("build_hybrid_context", "main_llm")

builder.add_conditional_edges(
    "retry_retrieval",
    route_or_error(route_after_retry_retrieval),
    {
        "error": "processing_error",
        "rag": "build_context",
        "hybrid": "build_hybrid_context",
    },
)

add_next("main_llm", "grounding_check")
builder.add_conditional_edges(
    "grounding_check",
    route_or_error(route_after_grounding),
    {
        "error": "processing_error",
        "pass": "finalize_observability",
        "retry_answer": "mark_generation_retry",
        "retry_retrieval": "retry_retrieval",
        "fail": "abstain",
    },
)
add_next("mark_generation_retry", "retry_answer")
add_next("retry_answer", "grounding_check")
add_next("abstain", "finalize_observability")
builder.add_edge("processing_error", "finalize_observability")
builder.add_edge("finalize_observability", END)

graph = builder.compile()


def run_graph(initial_state: PokemonState, *, config=None) -> PokemonState:
    """Exécute le graphe en conservant le dernier état en cas d'erreur du moteur."""
    state = dict(initial_state)
    state["trace"] = create_trace(state["question"])
    try:
        for snapshot in graph.stream(initial_state, config=config, stream_mode="values"):
            state.update(snapshot)
    except TraceFinalizationError:
        raise
    except Exception as exc:
        logger.exception("Échec de l'exécution LangGraph")
        state.update({
            "failed_step": "graph",
            "error_type": type(exc).__name__,
        })
        state.update(processing_error(state))
        state.update(finalize_node(state))
    return state


def print_answer(result: PokemonState, total_time: float) -> None:
    print()
    print("=" * 84)
    print("RÉPONSE")
    print("=" * 84)
    print(f"Route   : {result.get('route', '?')}")
    print(f"Intent  : {result.get('intent', '?')}")
    if result.get("pokemon"):
        print(f"Pokémon : {result['pokemon']}")
    print("\nRÉPONSE :")
    print(result.get("answer", "Aucune réponse."))

    print("\n" + "-" * 84)
    print("TIMINGS DU GRAPHE")
    print(f"Router      : {result.get('router_time', 0.0):.3f} s")
    if result.get("route") in {"RAG", "HYBRID"}:
        print(f"Retrieval   : {result.get('retrieval_time', 0.0):.3f} s")
        if result.get("retry_retrieval_time", 0.0):
            print(f"Retry retr. : {result.get('retry_retrieval_time', 0.0):.3f} s")
    if result.get("route") in {"STRUCTURED", "HYBRID"}:
        print(f"Structured  : {result.get('structured_time', 0.0):.3f} s")
        print(f"  ↳ Parser  : {result.get('structured_parse_time', 0.0):.3f} s")
        print(f"  ↳ SQL     : {result.get('structured_execution_time', 0.0):.6f} s")
        if result.get("route") == "STRUCTURED":
            print(f"  ↳ Format  : {result.get('structured_format_time', 0.0):.6f} s")
    if result.get("route") != "STRUCTURED":
        print(f"Context     : {result.get('context_time', 0.0):.3f} s")
        print(f"LLM         : {result.get('llm_time', 0.0):.3f} s")
        if result.get("llm_completion_tokens", 0):
            print(
                f"  ↳ Tokens  : {result.get('llm_completion_tokens', 0)} générés | "
                f"{result.get('llm_tokens_per_second', 0.0):.2f} tok/s"
            )
        print(f"Grounding   : {result.get('grounding_time', 0.0):.3f} s")
        if result.get("grounding_completion_tokens", 0):
            print(
                f"  ↳ Tokens  : {result.get('grounding_completion_tokens', 0)} générés | "
                f"{result.get('grounding_tokens_per_second', 0.0):.2f} tok/s"
            )
    if result.get("retry_llm_time", 0.0):
        print(f"Retry LLM   : {result.get('retry_llm_time', 0.0):.3f} s")
    print(f"TOTAL       : {total_time:.3f} s")
    print("-" * 84)

    if result.get("grounding_decision"):
        print(
            f"Grounding final : {result['grounding_decision']} — "
            f"{result.get('grounding_reason', '')}"
        )


def main() -> None:
    verbose = False
    print("Agent Pokémon hybride prêt.")
    print("Routes : STRUCTURED | RAG | HYBRID")
    print("Commandes : /verbose on | /verbose off | quit")

    while True:
        try:
            question = input("\nQuestion > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue

        command = question.lower()
        if command in {"quit", "exit", "q"}:
            break
        if command == "/verbose on":
            verbose = True
            print("Verbose activé.")
            continue
        if command == "/verbose off":
            verbose = False
            print("Verbose désactivé.")
            continue

        start = time.perf_counter()
        result = run_graph(
            {
                "question": question,
                "verbose": verbose,
                "retrieval_retry_count": 0,
                "generation_retry_count": 0,
            }
        )
        print_answer(result, time.perf_counter() - start)


if __name__ == "__main__":
    main()
