"""Budgets ADK : vrais objets SDK, aucune inférence."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from google.adk.models.llm_response import LlmResponse

from pokemon_rag.agent.context_budget import (
    after_model_abstention, before_model_budget, bounded_tool_result, after_tool_budget,
    MAX_TOOL_RESULT_BYTES, TOOL_FAILURE_ABSTENTION, _size as budget_size,
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
    assert "context_truncated" not in result
    assert result["tie"] and result["best_value"] == 100
    assert [(row["name_fr"],row["form_identifier"],row["Vitesse"]) for row in result["results"]] == [
        (f"Gagnant {i}",f"forme-{i}",100) for i in range(10)]
    assert data == original


@pytest.mark.parametrize("question,english", [
    ("Quelles capacités apprend ce Pokémon ?", False),
    ("Donne les noms anglais des capacités", True),
    ("Réponds en anglais", True),
    ("Sans noms anglais", False),
    ("Ne donne pas les noms anglais", False),
    ("Donne les noms français et anglais", True),
])
def test_localized_pairs_are_hidden_only_from_adk_when_not_requested(question, english):
    data = {"name_fr":"Pokémon français", "name_en":"English Pokemon", "identifier":"internal-id",
            "moves":[{"name_fr":"Combo-Griffe", "name_en":"Fury Swipes",
                      "type_fr":"Normal", "type_en":"Normal"},
                     {"name_fr":None, "name_en":"Untranslated"}]}
    original = deepcopy(data)
    ctx = SimpleNamespace(user_content=types.Content(parts=[types.Part(text=question)]))
    result = after_tool_budget(None, {}, ctx, {"structuredContent":data})
    assert ("name_en" in result) == english
    assert ("name_en" in result["moves"][0]) == english
    assert ("type_en" in result["moves"][0]) == english
    assert result["moves"][1]["name_en"] == "Untranslated"
    assert result["name_fr"] == data["name_fr"] and result["identifier"] == "internal-id"
    assert data == original


def test_oversized_question_short_circuits_before_model():
    ctx = SimpleNamespace(state={})
    req = request("🦕" * 10000)
    original = deepcopy(req.contents)
    response = before_model_budget(ctx, req)
    assert response.content.parts[0].text.startswith("Je n'ai pas pu")
    assert req.contents == original  # aucune suppression de contrainte pour rentrer dans le budget
    assert ctx.state == {}


@pytest.mark.parametrize("best,total,returned,cut,disable", [
    (True,2,2,False,True), (True,2,1,False,False),
    (False,20,10,False,True), (False,20,8,True,False), (False,0,0,False,True),
])
def test_final_ranking_formulation_omits_tools_only_for_complete_results(best,total,returned,cut,disable):
    data = {"operation":"search_pokemon", "stat_name_fr":"Défense", "best_only":best,
            "total_count":total,"returned_count":returned,"limit":10,"offset":0,
            "results":[{"name_fr":f"Pokémon {i}","base_stat_value":40} for i in range(returned)]}
    if cut:
        data["context_truncated"] = True
    req = request()
    req.contents.append(types.Content(role="user",parts=[types.Part(
        function_response=types.FunctionResponse(name="pokemon_search",response=data))]))
    req.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(name="pokemon_search")])]
    original = deepcopy(req.contents)
    assert before_model_budget(SimpleNamespace(state={}),req) is None
    assert (req.config.tools == []) == disable
    assert req.contents == original


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


def test_simple_nine_row_list_keeps_names_and_omits_tools_after_complete_response():
    data = {"operation":"search_pokemon","results":[{"name_fr":f"Nom {i}","pokemon_id":i,
             "form_id":i,"form_identifier":"internal", "generation":4} for i in range(9)],
            "total_count":9,"returned_count":9,"offset":0,"limit":30,"best_only":False,
            "catalogue_complete":False,"catalogue_missing_default_forms":[{"name_fr":"exception"}]}
    original = deepcopy(data)
    result = bounded_tool_result(data,question="Liste des légendaires de génération 4")
    assert result["results"] == [{"name_fr":f"Nom {i}"} for i in range(9)]
    assert "context_truncated" not in result and result["catalogue_complete"] is False
    assert "catalogue_missing_default_forms" not in result and data == original
    req = request()
    req.contents.append(types.Content(parts=[types.Part(function_response=types.FunctionResponse(name="pokemon_search",response=result))]))
    req.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(name="pokemon_search")])]
    assert before_model_budget(SimpleNamespace(state={}),req) is None
    assert req.config.tools == []


def test_nested_fr_en_condition_and_machine_item_use_french_only():
    data = {"conditions":{"known_move":{"fr":"Coup Double","en":"Double Hit"}},
            "machine_item":{"fr":"CT06","en":"TM06"}}
    assert bounded_tool_result(data) == {"conditions":{"known_move":{"fr":"Coup Double"}},
                                         "machine_item":{"fr":"CT06"}}


def test_multiple_requested_facts_keep_the_catalogue_and_requested_row_fields():
    req = request("Donne les types de Sinistrail et son numéro national")
    req.contents.append(types.Content(parts=[types.Part(function_response=types.FunctionResponse(
        name="pokemon_types",response={"operation":"get_pokemon_types","count":1,"rows":[{"type_1_fr":"Spectre"}]}))]))
    req.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(name="pokemon_pokedex_identity")])]
    assert before_model_budget(SimpleNamespace(state={}),req) is None
    assert req.config.tools
    result = bounded_tool_result({"operation":"search_pokemon","results":[{"name_fr":"Nom",
        "type_1_fr":"Spectre","type_2_fr":"Plante","generation":7,"pokemon_id":781}]},
        question="Donne les Pokémon avec leurs types et leurs générations")
    assert result["results"] == [{"name_fr":"Nom","type_1_fr":"Spectre","type_2_fr":"Plante","generation":7}]


def moves_response(count, **overrides):
    """Même forme que get_pokemon_moves : contrat MCP riche, non modifié par la projection."""
    return {"operation":"get_pokemon_moves","pokemon":"Espèce","pokemon_id":767,"form":None,
            "form_identifier":"internal","form_selection":"default","version_group":"sword-shield",
            "version_group_explicit":False,"version_selection":"latest_available","movepool_available":True,
            "move_properties":"current_not_historicized",
            "results":[{"move_id":i,"identifier":f"internal-move-{i}","name_fr":f"Capacité {i}","name_en":f"Move {i}",
                        "type_fr":"Eau","power":40 + i,"accuracy":100,"pp":20,"damage_class_fr":"physique",
                        "damage_class_id":2,"learning":[{"method":"egg","level":0},{"method":"level-up","level":12}]}
                       for i in range(count)],
            "total_count":count,"returned_count":count,"limit":100,"offset":0,"truncated":False,"has_more":False,
            **overrides}


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def formulation_request(name, result, question="Question courte"):
    req = request(question)
    req.contents.append(types.Content(role="user",parts=[types.Part(
        function_response=types.FunctionResponse(name=name,response=result))]))
    req.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(name=name)])]
    return req


@pytest.mark.parametrize("count", [3, 8, 10])
def test_small_moves_page_keeps_every_fact_drops_technical_fields_and_omits_tools(count):
    data = moves_response(count)
    original = deepcopy(data)
    result = bounded_tool_result(data, question="Quelles capacités physiques peut-il apprendre ?")
    assert data == original  # la réponse MCP n'est pas modifiée
    assert "context_truncated" not in result and len(result["results"]) == count
    assert result["results"][0] == {"name_fr":"Capacité 0","type_fr":"Eau","power":40,"accuracy":100,"pp":20,
        "damage_class_fr":"physique","learning":[{"method":"reproduction"},{"method":"montée de niveau","level":12}]}
    for technical in ("pokemon_id","form_identifier","form_selection","version_group_explicit","move_properties"):
        assert technical not in result
    assert result["pokemon"] == "Espèce" and result["movepool_available"] is True
    assert result["version_group_fr"] == "Pokémon Épée et Bouclier"
    assert (result["total_count"], result["returned_count"], result["truncated"], result["has_more"]) == (count, count, False, False)
    assert size(result) < size(original)
    req = formulation_request("pokemon_moves", result)
    assert before_model_budget(SimpleNamespace(state={}), req) is None
    assert req.config.tools == []  # une petite page complète se formule sans le catalogue


@pytest.mark.parametrize("change", [{"movepool_available":False}, {"context_truncated":True},
                                    {"returned_count":2}, {"offset":30}, {"error":"failure"}])
def test_incomplete_or_unavailable_moves_page_keeps_tools(change):
    result = {**bounded_tool_result(moves_response(3)), **change}
    req = formulation_request("pokemon_moves", result)
    before_model_budget(SimpleNamespace(state={}), req)
    assert req.config.tools


def test_large_movepool_reduces_optional_fields_before_cutting_rows():
    data = moves_response(90)
    names = [row["name_fr"] for row in data["results"]]
    plain = bounded_tool_result(data, question="Quelles capacités peut-il apprendre ?")
    assert [row["name_fr"] for row in plain["results"]] == names and "context_truncated" not in plain
    assert set(plain["results"][0]) == {"name_fr"}
    power = bounded_tool_result(data, question="Quelles capacités peut-il apprendre ?", args={"min_power":40})
    assert set(power["results"][0]) == {"name_fr","power"} and power["results"][5]["power"] == 45
    asked = bounded_tool_result(data, question="Quelles capacités apprend-il et à quel niveau, avec leur type ?")
    assert {"name_fr","type_fr","learning"} <= set(asked["results"][0])
    for result in (plain, power, asked):
        assert size(result) <= MAX_TOOL_RESULT_BYTES and result["total_count"] == 90
        assert result["returned_count"] == len(result["results"])
        assert bool(result.get("context_truncated")) == (len(result["results"]) < 90)
        assert bool(result.get("has_more")) == (len(result["results"]) < 90)


def test_ranking_rows_carry_the_value_under_its_french_statistic_name():
    for stat in ("PV", "Attaque Spéciale", "Total des statistiques de base"):
        data = {"operation":"search_pokemon","sort_by":"internal","stat_name_fr":stat,"best_only":False,
                "results":[{"name_fr":f"Pokémon {i}","base_stat_value":200 - i,"pokemon_id":i} for i in range(5)],
                "total_count":900,"returned_count":5,"limit":5,"offset":0,"truncated":True,"has_more":True}
        original = deepcopy(data)
        result = bounded_tool_result(data, question="Quels sont les 5 meilleurs ?")
        assert result["results"] == [{"name_fr":f"Pokémon {i}", stat:200 - i} for i in range(5)]
        assert result["stat_name_fr"] == stat and data == original
    best = {"operation":"search_pokemon","stat_name_fr":"Vitesse","best_only":True,"best_value":20,"tie":True,"tie_count":2,
            "results":[{"name_fr":"Premier","base_stat_value":20},{"name_fr":"Second","base_stat_value":20}],
            "total_count":2,"returned_count":2,"limit":30,"offset":0}
    result = bounded_tool_result(best, question="Quels sont les plus lents ?")
    assert result["results"] == [{"name_fr":"Premier","Vitesse":20},{"name_fr":"Second","Vitesse":20}]
    assert (result["best_value"], result["tie"], result["tie_count"]) == (20, True, 2)


def test_optional_null_arguments_are_simplified_only_in_the_model_view():
    schema = {"type":"object","required":["pokemon"],"properties":{
        "pokemon":{"type":"string"},
        "form":{"anyOf":[{"type":"string"},{"type":"null"}],"default":None},
        "category":{"anyOf":[{"const":"mega","type":"string"},{"type":"null"}],"default":None,"description":"Filtre"},
        "limit":{"type":"integer","default":30},
        "either":{"anyOf":[{"type":"string"},{"type":"integer"}]},
        "nullable_with_value":{"anyOf":[{"type":"integer"},{"type":"null"}],"default":3}}}
    declaration = types.FunctionDeclaration(name="test", parameters_json_schema=deepcopy(schema))
    req = request()
    req.config.tools = [types.Tool(function_declarations=[declaration])]
    assert before_model_budget(SimpleNamespace(state={}), req) is None
    properties = declaration.parameters_json_schema["properties"]
    assert properties["form"] == {"type":"string"}
    assert properties["category"] == {"const":"mega","type":"string","description":"Filtre"}
    for unchanged in ("pokemon","limit","either","nullable_with_value"):
        assert properties[unchanged] == schema["properties"][unchanged]
    assert declaration.parameters_json_schema["required"] == ["pokemon"]


def test_abridged_description_keeps_the_adk_fence_closed():
    begin, end = "<<<BEGIN_UNTRUSTED_TOOL_DESCRIPTION>>>", "<<<END_UNTRUSTED_TOOL_DESCRIPTION>>>"
    declaration = types.FunctionDeclaration(name="test", description=f"{begin}\nPremier paragraphe.\n\nSuite longue.\n{end}")
    req = request()
    req.config.tools = [types.Tool(function_declarations=[declaration])]
    for _ in range(2):  # le callback est rejoué à chaque appel du modèle
        assert before_model_budget(SimpleNamespace(state={}), req) is None
        assert declaration.description == f"{begin}\nPremier paragraphe.\n{end}"


def test_budget_abstention_logs_its_reason_and_sizes_without_content(caplog):
    with caplog.at_level("WARNING", logger="pokemon_rag.agent.context_budget"):
        assert before_model_budget(SimpleNamespace(state={}), request("🦕" * 10000)) is not None
        ctx = SimpleNamespace(state={"temp:model_calls": 4})
        assert before_model_budget(ctx, request()) is not None
    assert "request_too_large" in caplog.text and "too_many_model_calls" in caplog.text
    assert "12000" in caplog.text and "🦕" not in caplog.text


def test_latest_game_without_pair_title_is_named_in_french():
    result = bounded_tool_result(moves_response(2, version_group="champions"))
    assert result["version_group_fr"] == "Pokémon Champions"


def test_champions_training_method_is_labelled_in_french():
    data = moves_response(1, version_group="champions")
    data["results"][0]["learning"] = [{"method":"train","level":0}, {"method":"xd-shadow","level":0}]
    result = bounded_tool_result(data)
    # Une méthode sans libellé connu garde son identifiant plutôt qu'une traduction inventée.
    assert result["results"][0]["learning"] == [{"method":"entraînement"}, {"method":"xd-shadow"}]


TIMEOUT = {"error": "MCP tool execution failed: Request 'tools/call' timed out"}
REFUSAL = {"error": "invalid_explicit_constraints", "required_arguments": {"min_level": 10}}
TYPES = {"operation": "get_pokemon_types", "rows": [{"name_fr": "Mimiqui", "type_1_fr": "Spectre"}], "count": 1}
NO_PASSAGE = {"question": "à quoi ressemble reshiram ?", "pokemon": "reshiram", "results": []}
PASSAGES = {"question": "À quoi ressemble Mimiqui ?", "pokemon": "Mimiqui", "results": [{"text": "Mimiqui porte un chiffon."}]}
NO_MATCH = {"operation": "search_pokemon", "results": [], "total_count": 0, "returned_count": 0, "limit": 30, "offset": 0}


def model_turn(*results, answer=None, call=None):
    """Déroule les deux callbacks autour d'une réponse simulée du modèle ; renvoie le texte final."""
    req = request("À quoi ressemble Mimiqui ?")
    for result in results:
        name = {"get_pokemon_types": "pokemon_types", "search_pokemon": "pokemon_search"}.get(
            result.get("operation"), "pokemon_rag_search")
        req.contents.append(types.Content(role="user", parts=[types.Part(
            function_response=types.FunctionResponse(name=name, response=result))]))
    ctx = SimpleNamespace(state={})
    assert before_model_budget(ctx, req) is None
    part = types.Part(function_call=types.FunctionCall(name=call, args={})) if call else types.Part(text=answer)
    response = LlmResponse(content=types.Content(role="model", parts=[part]))
    replaced = after_model_abstention(ctx, response)
    return (replaced or response).content.parts[0]


@pytest.mark.parametrize("results", [
    [TIMEOUT],                                      # panne : cas observé dans le conteneur
    [REFUSAL],                                      # refus du guard resté sans appel compatible
    [bounded_tool_result({"isError": True})],       # erreur signalée par le serveur MCP
    [TIMEOUT, REFUSAL, TIMEOUT],                    # plusieurs tentatives, aucune valide
    [NO_PASSAGE],                                   # recherche documentaire vide : cas « reshiram »
    [NO_PASSAGE, TIMEOUT],
])
def test_answer_written_after_only_failed_tool_calls_is_replaced(results, caplog):
    # Régression : après un délai dépassé, le modèle décrivait Mimiqui de mémoire.
    with caplog.at_level("WARNING", logger="pokemon_rag.agent.context_budget"):
        part = model_turn(*results, answer="Mimiqui ressemble à un Pikachu en chiffon avec des oreilles pointues.")
    assert part.text == TOOL_FAILURE_ABSTENTION
    assert "tool_failure_abstention" in caplog.text and "Pikachu" not in caplog.text


@pytest.mark.parametrize("results", [
    [TYPES],                # résultat valide
    [TIMEOUT, TYPES],       # échec puis nouvelle tentative réussie
    [TYPES, TIMEOUT],       # un fait valide existe déjà
    [PASSAGES],             # passages trouvés
    [NO_PASSAGE, PASSAGES], # recherche relancée avec succès
    [NO_MATCH],             # liste structurée vide : « aucun Pokémon ne correspond » est un fait
    [],                     # aucun outil appelé : hors du périmètre de ce contrôle
])
def test_answer_backed_by_a_valid_tool_result_is_kept(results):
    assert model_turn(*results, answer="Mimiqui est de type Spectre.").text == "Mimiqui est de type Spectre."


def test_retrying_a_tool_after_a_failure_is_not_blocked():
    part = model_turn(TIMEOUT, call="pokemon_rag_search")
    assert part.function_call.name == "pokemon_rag_search" and part.text is None


def test_agent_applies_the_abstention_after_every_model_answer():
    from pokemon_rag.agent.agent import root_agent
    assert root_agent.after_model_callback is after_model_abstention


def test_tool_measures_go_to_the_session_state_and_never_to_the_model():
    context = SimpleNamespace(user_content=None, state={})
    passages = {"question": "À quoi ressemble Mimiqui ?", "pokemon": "Mimiqui",
                "results": [{"text": "Mimiqui porte un chiffon."}],
                "timings": {"vector": 0.05, "reranker": 1.1, "total": 1.23, "startup": {"total": 54.3}}}
    types_result = {"operation": "get_pokemon_types", "rows": [{"name_fr": "Mimiqui"}], "count": 1,
                    "execution_time": 0.048}
    seen = [after_tool_budget(SimpleNamespace(name=name), {}, context, {"structuredContent": deepcopy(result)})
            for name, result in (("pokemon_rag_search", passages), ("pokemon_types", types_result))]
    # Le modèle ne reçoit aucune mesure : son budget de contexte est inchangé.
    assert "timings" not in seen[0] and "execution_time" not in seen[1]
    assert "54.3" not in json.dumps(seen) and "0.048" not in json.dumps(seen)
    assert seen[0]["results"] == passages["results"]
    assert context.state["tool_timings"] == [
        {"tool": "pokemon_rag_search", "timings": passages["timings"], "passages": 1},
        {"tool": "pokemon_types", "execution_time": 0.048},
    ]


def test_failed_tool_still_records_an_entry_so_later_measures_stay_aligned():
    context = SimpleNamespace(user_content=None, state={})
    after_tool_budget(SimpleNamespace(name="pokemon_rag_search"), {}, context, dict(TIMEOUT))
    after_tool_budget(SimpleNamespace(name="pokemon_types"), {}, context, {"isError": True})
    assert context.state["tool_timings"] == [{"tool": "pokemon_rag_search"}, {"tool": "pokemon_types"}]


def test_callback_context_without_state_is_tolerated():
    result = after_tool_budget(SimpleNamespace(name="pokemon_types"), {}, SimpleNamespace(user_content=None),
                               {"structuredContent": {"operation": "get_pokemon_types", "rows": [], "count": 0}})
    assert result["operation"] == "get_pokemon_types"


def documentary_request(result, question="À quoi ressemble Mimiqui ?"):
    """Retour de recherche documentaire devant un catalogue de la taille du vrai (environ 8 Ko)."""
    req = request(question)
    req.contents.append(types.Content(role="user", parts=[types.Part(
        function_response=types.FunctionResponse(name="pokemon_rag_search", response=result))]))
    req.config.tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=f"outil_{index}", description="Règle d'appel. " * 55) for index in range(10)])]
    return req


LONG_PASSAGES = {"question": "À quoi ressemble Mimiqui ?", "pokemon": "Mimiqui",
                 "results": [{"text": "Mimiqui se cache sous un chiffon. " * 20, "section_path": "Description"}] * 4}


def test_passages_are_formulated_without_the_catalogue_instead_of_a_budget_abstention():
    # Régression : catalogue + passages dépassaient le budget, la réponse documentaire était abandonnée.
    assert size(LONG_PASSAGES) > 2500
    req = documentary_request(LONG_PASSAGES)
    assert budget_size(req.config.tools) > 7500
    assert before_model_budget(SimpleNamespace(state={}), req) is None
    assert req.config.tools == []
    assert req.contents[-1].parts[0].function_response.response == LONG_PASSAGES  # aucun passage retiré


@pytest.mark.parametrize("result, question", [
    (NO_PASSAGE, "À quoi ressemble Mimiqui ?"),                       # recherche vide : nouvelle tentative possible
    (TIMEOUT, "À quoi ressemble Mimiqui ?"),                          # erreur : nouvelle tentative possible
    (PASSAGES, "Décris l'apparence de Mimiqui et ses types."),        # demande composée : autre outil à appeler
])
def test_catalogue_stays_when_another_tool_call_may_still_be_needed(result, question):
    req = documentary_request(result, question)
    before_model_budget(SimpleNamespace(state={}), req)
    assert req.config.tools
