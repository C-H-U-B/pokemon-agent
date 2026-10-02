"""Budget local de contexte ADK, sans tokeniseur ou appel de modèle.

Le volume UTF-8 sérialisé est une borne conservatrice, pas un comptage exact
des tokens Qwen. Les réserves couvrent les tokens de réponse et le protocole.
"""
from copy import deepcopy
import json
from typing import Any

from google.adk.models.llm_response import LlmResponse
from google.genai import types


MAX_REQUEST_BYTES = 12_000
MAX_TOOL_RESULT_BYTES = 3_000
MAX_MODEL_CALLS = 4
MAX_OUTPUT_TOKENS = 1_024


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True, mode="json")
    return value


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_dump).encode("utf-8"))


def _without_schema_titles(schema: Any) -> Any:
    """Retire les annotations title ; conserve propriétés nommées title et validation."""
    if isinstance(schema, list):
        return [_without_schema_titles(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {key: (item if key in {"default", "enum", "const", "examples", "dependentRequired"}
                  else {name: _without_schema_titles(value) for name, value in item.items()}
                  if key in {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
                  else _without_schema_titles(item))
            for key, item in schema.items() if key != "title"}


def bounded_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    """Enlève la copie MCP textuelle et réduit les listes avec troncature explicite."""
    if response.get("isError") or response.get("is_error"):
        return {"error": "mcp_tool_error", "message": "L'outil a signalé une erreur ; aucun fait ne peut en être déduit."}
    data = response.get("structuredContent", response.get("structured_content"))
    if data is None and isinstance(response.get("content"), list):
        content = response["content"]
        if len(content) == 1 and content[0].get("type") == "text":
            try:
                data = json.loads(content[0]["text"])
            except (ValueError, KeyError):
                pass
    data = deepcopy(data if isinstance(data, dict) else response)
    if _size(data) <= MAX_TOOL_RESULT_BYTES:
        return data
    # Le top N doit conserver ses noms/valeurs avant de réduire une page.
    # Les identifiants internes et traductions anglaises ne sont pas nécessaires
    # à la formulation d'un classement ; l'API MCP originale reste inchangée.
    if (data.get("operation") == "search_pokemon" and data.get("stat_name_fr")
            and isinstance(data.get("results"), list)):
        for row in data["results"]:
            if isinstance(row, dict):
                for field in ("name_en", "pokemon_id", "form_id"):
                    row.pop(field, None)
        data["context_compacted"] = True
        if _size(data) <= MAX_TOOL_RESULT_BYTES:
            return data
    keys = [key for key in ("results", "moves", "rows", "evolutions") if isinstance(data.get(key), list)]
    lengths = {key: len(data[key]) for key in keys}
    data["context_truncated"] = True
    data["truncated"] = True
    if len(keys) == 1:
        key = keys[0]
        data.setdefault("total_count", data.get("count", lengths[key]))
        data["returned_count"] = len(data[key])
        data["has_more"] = True
    while keys and _size(data) > MAX_TOOL_RESULT_BYTES:
        key = max(keys, key=lambda item: _size(data[item]))
        if not data[key]:
            keys.remove(key)
            continue
        data[key].pop()
        if len(lengths) == 1:
            data["returned_count"] = len(data[key])
    if _size(data) > MAX_TOOL_RESULT_BYTES or (lengths and not any(data[key] for key in lengths)):
        return {"error": "tool_result_too_large", "context_truncated": True,
                "message": "Résultat trop volumineux. Utilisez un filtre ou une page plus petite ; aucun résultat vide ne peut en être déduit."}
    return data


def after_tool_budget(tool: Any, args: dict, tool_context: Any, tool_response: dict) -> dict:
    """Adapter uniquement la réponse destinée à ADK, sans changer l'API MCP."""
    return bounded_tool_result(tool_response)


def before_model_budget(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    """Réponse locale avant dépassement du budget ou répétition excessive."""
    config = llm_request.config
    config.max_output_tokens = min(config.max_output_tokens or MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS)
    for tool in config.tools or []:
        for declaration in getattr(tool, "function_declarations", None) or []:
            if declaration.description:
                declaration.description = declaration.description.split("\n\n", 1)[0][:300]
            if declaration.parameters_json_schema:
                declaration.parameters_json_schema = _without_schema_titles(declaration.parameters_json_schema)
    calls = callback_context.state.get("temp:model_calls", 0)
    payload = {"contents": llm_request.contents, "system_instruction": config.system_instruction,
               "tools": config.tools}
    if calls >= MAX_MODEL_CALLS or _size(payload) > MAX_REQUEST_BYTES:
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=(
            "Je n'ai pas pu obtenir une réponse fiable dans les limites de traitement. "
            "Précisez les filtres ou demandez une liste plus courte."))]))
    callback_context.state["temp:model_calls"] = calls + 1
    return None
