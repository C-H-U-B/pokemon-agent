"""Budget local de contexte ADK, sans tokeniseur ou appel de modèle.

Le volume UTF-8 sérialisé est une borne conservatrice, pas un comptage exact
des tokens Qwen. Les réserves couvrent les tokens de réponse et le protocole.
"""
from copy import deepcopy
import json
import re
from typing import Any

from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pokemon_rag.agent.tool_guard import _extract_user_text
from pokemon_rag.constraints.query_constraints import normalize, VERSION_GROUP_NAMES_FR


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


def _french_fields(value: Any) -> Any:
    """Masque les traductions anglaises seulement quand leur paire française existe."""
    if isinstance(value, list):
        return [_french_fields(item) for item in value]
    if isinstance(value, dict):
        return {key: _french_fields(item) for key, item in value.items()
                if not ((key.endswith("_en") and value.get(key[:-3] + "_fr"))
                        or (key == "en" and value.get("fr")))}
    return value


def _english_requested(question: str) -> bool:
    text = normalize(question)
    if re.search(r"(?:^|-)(?:pas|sans|aucun|jamais)-(?:de-|d-|les-|le-|des-)?(?:noms?-)?anglais", text):
        return False
    return bool(re.search(r"(?:^|-)(?:(?:en|noms?|termes?|traduction)-anglais(?:e|s|es)?|"
                          r"francais-et-anglais|bilingue)(?:-|$)", text))


def _presentation_data(data: dict, question: str, args: dict) -> dict:
    """Projection ADK uniquement ; conserver compte, pagination et faits nécessaires."""
    operation = data.get("operation")
    if operation == "search_pokemon":
        data.pop("catalogue_missing_default_forms", None)
        data.pop("catalogue", None)
        fields = {"name_fr", "name_en", "base_stat_value"}
        if args.get("pokedex_number") is not None or re.search(r"numero|pokedex|identite", normalize(question)):
            fields.add("national_number")
        text = normalize(question)
        for noun, requested in (("types?", {"type_1_fr","type_2_fr"}),
                                ("generations?", {"generation"}),
                                ("classifications?", {"legendary","mythical"})):
            if re.search(rf"(?:^|-)(?:(?:et|avec)-(?:leurs?-|ses-|son-|sa-|les-|le-|la-|des-)?|leurs?-){noun}(?:-|$)",text):
                fields.update(requested)
        if not question:
            fields.update({"form_identifier", "national_number", "type_1_fr", "type_2_fr", "generation", "legendary", "mythical", "version_group"})
        data["results"] = [{key:value for key,value in row.items() if key in fields}
                           for row in data.get("results", [])]
        data["context_compacted"] = True
    elif operation in {"get_level_up_moves", "get_machine_moves", "get_move_learning_methods", "get_pokemon_moves"}:
        for key in ("moves", "methods"):
            for row in data.get(key, []):
                for field in ("pokemon_id", "move_id", "identifier", "order", "move_order"):
                    row.pop(field, None)
                if data.get("version_group"):
                    row.pop("version_group", None)
                item = row.get("machine_item")
                if isinstance(item,dict) and item.get("fr") and not _english_requested(question):
                    row["machine_item_fr"] = item["fr"]
                    row.pop("machine_item",None)
                    row.pop("machine_number",None)  # CT06 contient déjà le numéro.
                if row.get("method") == "machine":
                    row.pop("level", None)  # 0 n'est pas un niveau d'obtention de CT.
        data["context_compacted"] = True
    if operation:
        data.pop("execution_time", None)
        def game_names(value):
            if isinstance(value,list):
                for item in value:
                    game_names(item)
            elif isinstance(value,dict):
                version = value.get("version_group")
                if version in VERSION_GROUP_NAMES_FR:
                    value["version_group_fr"] = VERSION_GROUP_NAMES_FR[version]
                for item in list(value.values()):
                    game_names(item)
        game_names(data)
    return data


def bounded_tool_result(response: dict[str, Any], *, keep_english: bool = False,
                        question: str = "", args: dict | None = None) -> dict[str, Any]:
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
    if not keep_english:
        data = _french_fields(data)
    data = _presentation_data(data, question, args or {})
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
    question = _extract_user_text(getattr(tool_context, "user_content", None))
    return bounded_tool_result(tool_response, keep_english=_english_requested(question), question=question, args=args)


def _complete_structured_response(contents: list) -> bool:
    """Une page structurée complète ne nécessite plus de sélection d'outil.

    Conserve les outils en cas d'erreur, de troncature ADK ou de gagnants manquants.
    Un top N complet peut avoir has_more=true : le reste du catalogue n'est pas
    demandé. Une page de superlatif doit au contraire contenir tous les gagnants.
    """
    if not contents:
        return False
    responses = [part.function_response for part in contents[-1].parts or [] if part.function_response]
    if len(responses) != 1:
        return False
    result = responses[0].response
    if result.get("error") or result.get("context_truncated"):
        return False
    if responses[0].name != "pokemon_search":
        keys = {"pokemon_level_up_moves":"moves", "pokemon_machine_moves":"moves",
                "pokemon_move_learning_methods":"methods", "pokemon_types":"rows",
                "pokemon_pokedex_identity":"rows", "pokemon_evolutions":"evolutions"}
        key = keys.get(responses[0].name)
        return bool(key and isinstance(result.get(key), list)
                    and result.get("count") == len(result[key]))
    if result.get("operation") != "search_pokemon":
        return False
    total, returned, limit = (result.get(key) for key in ("total_count", "returned_count", "limit"))
    if any(type(value) is not int or value < 0 for value in (total, returned, limit)):
        return False
    if returned != len(result.get("results", [])) or result.get("offset") != 0:
        return False
    return returned == total if result.get("best_only") else returned == min(total, limit)


def before_model_budget(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    """Réponse locale avant dépassement du budget ou répétition excessive."""
    config = llm_request.config
    config.max_output_tokens = min(config.max_output_tokens or MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS)
    question = " ".join(part.text for content in llm_request.contents if content.role == "user"
                        for part in content.parts or [] if part.text)
    compound = re.search(r"(?:^|-)(?:et|puis|ainsi-que)-(?:leurs?-|ses-|son-|sa-|les-|le-|la-)?"
                         r"(?:types?|numeros?|evolutions?|attaques?|capacites?|statistiques?|vitesse|defense)(?:-|$)",normalize(question))
    documentary = re.search(r"(?:^|-)(?:apparence|habitat|comportement|origine|histoire|description|decris)(?:-|$)",normalize(question))
    if not compound and not documentary and _complete_structured_response(llm_request.contents):
        # Phase de formulation, comme dans le client MCP : les faits restent
        # intégralement présents, sans transmettre à nouveau le catalogue.
        config.tools = []
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
