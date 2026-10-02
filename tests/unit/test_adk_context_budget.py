"""Budgets ADK : vrais objets SDK, aucune inférence."""
from copy import deepcopy
import json
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from pokemon_rag.agent.context_budget import (
    before_model_budget, bounded_tool_result, MAX_TOOL_RESULT_BYTES,
)


def request(text="Question courte"):
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text=text)])])


def test_mcp_structured_result_is_not_sent_twice():
    data = {"results": [{"name_fr": "Regieleki", "base_speed": 200}], "total_count": 1}
    response = {"structuredContent": data, "content": [{"type": "text", "text": json.dumps(data)}], "isError": False}
    original = deepcopy(response)
    assert bounded_tool_result(response) == data
    assert response == original


def test_large_result_retains_prefix_counts_and_context():
    original = {"moves": [{"name_fr": f"Capacité {index}", "description": "é" * 100} for index in range(200)],
                "count": 200, "version_group": "sun-moon", "form": "alola"}
    result = bounded_tool_result(original)
    assert 0 < result["returned_count"] < 200
    assert result["moves"] == original["moves"][:result["returned_count"]]
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_TOOL_RESULT_BYTES
    assert result["total_count"] == result["count"] == 200
    assert result["truncated"] and result["context_truncated"]
    assert result["version_group"] == "sun-moon" and result["form"] == "alola"
    assert len(original["moves"]) == 200


def test_mcp_failure_is_not_converted_to_successful_facts():
    result = bounded_tool_result({"isError": True, "structuredContent": {"results": [{"name_fr": "Invention"}]}})
    assert result["error"] == "mcp_tool_error"
    assert "results" not in result


def test_single_oversized_document_is_an_error_not_an_empty_retrieval():
    result = bounded_tool_result({"results": [{"text": "texte" * 10000, "source": "page"}]})
    assert result["error"] == "tool_result_too_large"
    assert "results" not in result


def test_existing_pagination_total_is_preserved():
    result = bounded_tool_result({"results": [{"name_fr": "é" * 100} for _ in range(30)],
                                  "total_count": 247, "offset": 30, "limit": 30})
    assert result["total_count"] == 247 and result["offset"] == 30
    assert result["returned_count"] < 30 and result["has_more"]


def test_stat_ranking_compacts_technical_fields_before_cutting_winners():
    data = {"operation":"search_pokemon", "stat_name_fr":"Vitesse", "tie":True, "tie_count":10,
            "best_value":100, "total_count":10, "returned_count":10,
            "results":[{"name_fr":f"Gagnant {i}", "form_identifier":f"forme-{i}", "base_stat_value":100,
                        "name_en":"English name"*20, "pokemon_id":i, "form_id":i} for i in range(10)]}
    original = deepcopy(data)
    result = bounded_tool_result(data)
    assert len(result["results"]) == result["returned_count"] == result["tie_count"] == 10
    assert result["context_compacted"] and "context_truncated" not in result
    assert result["tie"] and result["best_value"] == 100
    assert [(row["name_fr"],row["form_identifier"],row["base_stat_value"]) for row in result["results"]] == [
        (f"Gagnant {i}",f"forme-{i}",100) for i in range(10)]
    assert data == original


def test_oversized_question_short_circuits_before_model():
    ctx = SimpleNamespace(state={})
    req = request("🦕" * 10000)
    original = deepcopy(req.contents)
    response = before_model_budget(ctx, req)
    assert response.content.parts[0].text.startswith("Je n'ai pas pu")
    assert req.contents == original  # aucune suppression de contrainte pour rentrer dans le budget
    assert ctx.state == {}


def test_call_limit_is_per_context_and_returns_final_text():
    ctx = SimpleNamespace(state={})
    for _ in range(4):
        assert before_model_budget(ctx, request()) is None
    assert before_model_budget(ctx, request()).content.role == "model"
    assert before_model_budget(SimpleNamespace(state={}), request()) is None


def test_tool_descriptions_shrink_without_changing_arguments():
    declaration = types.FunctionDeclaration(name="pokemon_search", description="Recherche Pokémon.\n\n" + "documentation" * 1000,
        parameters_json_schema={"type": "object", "properties": {"sort_by": {"type": "string", "enum": ["speed"]}}, "required": ["sort_by"]})
    req = request()
    req.config.tools = [types.Tool(function_declarations=[declaration])]
    schema = deepcopy(declaration.parameters_json_schema)
    assert before_model_budget(SimpleNamespace(state={}), req) is None
    assert declaration.description == "Recherche Pokémon."
    assert declaration.parameters_json_schema == schema


def test_schema_titles_removed_without_losing_validation_or_title_parameter():
    declaration = types.FunctionDeclaration(name="test", parameters_json_schema={
        "title":"Generated input", "type":"object", "required":["title","limit"],
        "properties":{"title":{"title":"A title", "type":"string", "minLength":1},
                      "limit":{"title":"Limit", "type":"integer", "minimum":0, "maximum":100},
                      "mode":{"title":"Mode", "enum":["asc","desc"], "description":"Ordre SQL"}}})
    req = request()
    req.config.tools = [types.Tool(function_declarations=[declaration])]
    assert before_model_budget(SimpleNamespace(state={}), req) is None
    assert declaration.parameters_json_schema == {"type":"object", "required":["title","limit"],
        "properties":{"title":{"type":"string", "minLength":1},
                      "limit":{"type":"integer", "minimum":0, "maximum":100},
                      "mode":{"enum":["asc","desc"], "description":"Ordre SQL"}}}
