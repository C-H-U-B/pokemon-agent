"""Historique des tentatives et agrégats, sans additionner les débits."""

TIMING_FIELDS = {
    "router": "router_time", "retrieval": "retrieval_time",
    "retry_retrieval": "retry_retrieval_time", "structured": "structured_time",
    "structured_parse": "structured_parse_time",
    "structured_execution": "structured_execution_time",
    "structured_format": "structured_format_time", "context": "context_time",
    "main_llm": "llm_time", "grounding": "grounding_time",
    "retry_llm": "retry_llm_time",
}
STEP_TIMINGS = {
    "router": "router", "retrieve_documents": "retrieval",
    "retry_retrieval": "retry_retrieval", "retrieve_structured_data": "structured",
    "format_structured_answer": "structured_format", "build_context": "context",
    "build_hybrid_context": "context", "main_llm": "main_llm",
    "grounding_check": "grounding", "retry_answer": "retry_llm",
}
LLM_STEPS = {"main_llm": "llm", "grounding_check": "grounding", "retry_answer": "retry_llm"}
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def record_attempt(name, state, result, duration):
    previous = state.get("attempts", [])
    timings = {
        label: float(result[field]) for label, field in TIMING_FIELDS.items()
        if field in result
    }
    if name in STEP_TIMINGS:
        timings[STEP_TIMINGS[name]] = duration
    attempt = {
        "step": name,
        "attempt": 1 + sum(item["step"] == name for item in previous),
        "duration_seconds": duration,
        "status": "ERROR" if result.get("execution_status") == "ERROR" else "SUCCESS",
        "timings": timings,
    }
    if result.get("error_type"):
        attempt["error_type"] = result["error_type"]
    prefix = LLM_STEPS.get(name)
    if prefix and result.get("llm_called", True):
        known = result.get(f"{prefix}_usage_known", False)
        attempt["llm"] = {
            "name": prefix,
            **{key: result.get(f"{prefix}_{key}") if known else None for key in TOKEN_FIELDS},
        }
    return [*previous, attempt]


def aggregate_attempts(attempts):
    timings, steps, llms = {}, {}, {}
    for attempt in attempts:
        step = steps.setdefault(attempt["step"], {"calls": 0, "errors": 0, "duration_seconds": 0.0})
        step["calls"] += 1
        step["errors"] += attempt["status"] == "ERROR"
        step["duration_seconds"] += attempt["duration_seconds"]
        for name, seconds in attempt["timings"].items():
            timings[name] = timings.get(name, 0.0) + seconds
        usage = attempt.get("llm")
        if usage is None:
            continue
        metrics = llms.setdefault(usage["name"], {
            "calls": 0, "errors": 0, "duration_seconds": 0.0,
            "unknown_usage_calls": 0,
            "known_tokens": {key: 0 for key in TOKEN_FIELDS},
        })
        metrics["calls"] += 1
        metrics["errors"] += attempt["status"] == "ERROR"
        metrics["duration_seconds"] += attempt["duration_seconds"]
        metrics["unknown_usage_calls"] += any(usage[key] is None for key in TOKEN_FIELDS)
        for key in TOKEN_FIELDS:
            if usage[key] is not None:
                metrics["known_tokens"][key] += usage[key]
    for metrics in llms.values():
        complete = metrics["unknown_usage_calls"] == 0
        metrics["usage_complete"] = complete
        for key in TOKEN_FIELDS:
            metrics[key] = metrics["known_tokens"][key] if complete else None
        duration = metrics["duration_seconds"]
        metrics["tokens_per_second"] = (
            metrics["completion_tokens"] / duration if complete and duration > 0 else None
        )
    return timings, steps, llms
