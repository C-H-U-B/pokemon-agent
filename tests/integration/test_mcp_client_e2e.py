"""Parcours du client : intégration isolée et E2E réel marqué llm/real_data/models.

Les tests isolés simulent les frontières MCP et LLM, pas les fonctions du client.
Les E2E réels vérifient le choix et l'exécution ; le texte reste à relire pour
évaluer sa fidélité, car le client n'applique pas le grounding du graphe.
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from pokemon_rag.client import mcp_client as client


QUESTION = "Quels sont les types de Pikachu ?"
ANSWER = "Pikachu est de type Électrik."
SELECTION = {"tool": "pokemon_types", "arguments": {"pokemon": "Pikachu"}}
DATA = {"pokemon": "Pikachu", "types": ["Électrik"]}


def response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def journey(monkeypatch):
    """Vrais objets SDK ; frontières simulées pour isoler les erreurs du client."""
    tool = Tool(
        name="pokemon_types",
        description="Types du Pokémon",
        input_schema={
            "type": "object",
            "properties": {"pokemon": {"type": "string"}},
            "required": ["pokemon"],
        },
    )
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[tool])),
        call_tool=AsyncMock(return_value=CallToolResult(content=[], structured_content=DATA)),
    )
    events = []
    parameters = []

    @asynccontextmanager
    async def transport(server):
        parameters.append(server)
        events.append("transport_open")
        try:
            yield ("read", "write")
        finally:
            events.append("transport_closed")

    @asynccontextmanager
    async def session_context(read, write):
        assert (read, write) == ("read", "write")
        events.append("session_open")
        try:
            yield session
        finally:
            events.append("session_closed")

    create = Mock(side_effect=[response(json.dumps(SELECTION)), response(ANSWER)])
    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "stdio_client", transport)
    monkeypatch.setattr(client, "ClientSession", session_context)
    monkeypatch.setattr(client, "create_llm_client", lambda: llm)
    yield SimpleNamespace(session=session, create=create, tool=tool, parameters=parameters)
    if events:
        assert events == ["transport_open", "session_open", "session_closed", "transport_closed"]


def test_complete_journey_discovers_schema_calls_tool_and_transmits_result(journey):
    assert asyncio.run(client.ask(QUESTION)) == ANSWER
    journey.session.initialize.assert_awaited_once()
    journey.session.list_tools.assert_awaited_once()
    journey.session.call_tool.assert_awaited_once_with("pokemon_types", arguments={"pokemon": "Pikachu"})
    assert journey.parameters[0].command == sys.executable
    assert journey.parameters[0].args == ["-m", client.SERVER_MODULE]
    assert journey.create.call_count == 2
    selection_prompt = journey.create.call_args_list[0].kwargs["messages"][1]["content"]
    assert QUESTION in selection_prompt
    payload = json.loads(selection_prompt.split("Tools MCP disponibles :\n", 1)[1])
    assert payload == [{"name": journey.tool.name, "description": journey.tool.description,
                        "input_schema": journey.tool.input_schema}]
    answer_prompt = journey.create.call_args_list[1].kwargs["messages"][1]["content"]
    assert QUESTION in answer_prompt
    assert json.loads(answer_prompt.split("Résultat disponible :\n", 1)[1]) == DATA


@pytest.mark.parametrize("content", [
    json.dumps(SELECTION),
    "```json\n" + json.dumps(SELECTION) + "\n```",
    "Sélection : " + json.dumps(SELECTION),
])
def test_selection_formats(journey, content):
    journey.create.side_effect = [response(content), response(ANSWER)]
    assert asyncio.run(client.ask(QUESTION)) == ANSWER


@pytest.mark.parametrize("content", [
    None, "", "aucun outil", "{JSON invalide}", "{}",
    '{"tool": null}', '{"tool": 42}', '{"tool": ""}',
    '{"tool": "outil_inconnu"}',
    '{"tool": "pokemon_types", "arguments": []}',
    '{"tool": "pokemon_types", "arguments": null}',
])
def test_invalid_selection_stops_before_execution(journey, content):
    journey.create.side_effect = [response(content)]
    with pytest.raises(ValueError):
        asyncio.run(client.ask(QUESTION))
    journey.session.call_tool.assert_not_awaited()
    assert journey.create.call_count == 1


def test_empty_catalog_rejects_invented_tool(journey):
    journey.session.list_tools.return_value = SimpleNamespace(tools=[])
    with pytest.raises(ValueError, match="inconnu"):
        asyncio.run(client.ask(QUESTION))
    journey.session.call_tool.assert_not_awaited()


@pytest.mark.parametrize("result, expected", [
    (CallToolResult(content=[TextContent(type="text", text="ignored")], structured_content=DATA), DATA),
    (CallToolResult(content=[], structured_content={}), {}),
    (CallToolResult(content=[TextContent(type="text", text=json.dumps(DATA))]), DATA),
    (CallToolResult(content=[TextContent(type="text", text="Texte source")]), "Texte source"),
    (CallToolResult(content=[TextContent(type="text", text="A"), TextContent(type="text", text="B")]), ["A", "B"]),
    (CallToolResult(content=[]), []),
    (CallToolResult(content=[], structured_content={"results": []}), {"results": []}),
])
def test_result_formats_reach_answer_model(journey, result, expected):
    journey.session.call_tool.return_value = result
    assert asyncio.run(client.ask(QUESTION)) == ANSWER
    prompt = journey.create.call_args.kwargs["messages"][1]["content"]
    assert json.loads(prompt.split("Résultat disponible :\n", 1)[1]) == expected


def test_tool_error_never_generates_an_answer(journey):
    journey.session.call_tool.return_value = CallToolResult(
        is_error=True, content=[TextContent(type="text", text="Erreur technique")]
    )
    with pytest.raises(RuntimeError, match="pokemon_types"):
        asyncio.run(client.ask(QUESTION))
    assert journey.create.call_count == 1


@pytest.mark.parametrize("stage, model_calls", [("initialize", 0), ("list_tools", 0), ("call_tool", 1)])
def test_mcp_failures_propagate_and_close_session(journey, stage, model_calls):
    getattr(journey.session, stage).side_effect = ConnectionError("MCP indisponible")
    with pytest.raises(ConnectionError, match="MCP indisponible"):
        asyncio.run(client.ask(QUESTION))
    assert journey.create.call_count == model_calls


@pytest.mark.parametrize("stage", ["selection", "answer"])
def test_model_failures_propagate_and_close_session(journey, stage):
    error = TimeoutError("Modèle indisponible")
    journey.create.side_effect = [error] if stage == "selection" else [response(json.dumps(SELECTION)), error]
    with pytest.raises(TimeoutError, match="Modèle indisponible"):
        asyncio.run(client.ask(QUESTION))
    assert journey.session.call_tool.await_count == (stage == "answer")


def test_transport_startup_failure_does_not_call_model(journey, monkeypatch):
    @asynccontextmanager
    async def unavailable_transport(_):
        raise OSError("Serveur MCP introuvable")
        yield  # pragma: no cover -- définit le contexte asynchrone

    monkeypatch.setattr(client, "stdio_client", unavailable_transport)
    with pytest.raises(OSError, match="Serveur MCP introuvable"):
        asyncio.run(client.ask(QUESTION))
    journey.create.assert_not_called()


def test_selected_constraints_are_forwarded_without_loss(journey):
    arguments = {"pokemon": "Noadkoko", "form": "alola", "version_group": "sun-moon",
                 "min_level": 21, "max_level": 39}
    journey.session.list_tools.return_value = SimpleNamespace(tools=[Tool(
        name="pokemon_level_up_moves", input_schema={"type": "object"}
    )])
    journey.create.side_effect = [response(json.dumps({
        "tool": "pokemon_level_up_moves", "arguments": arguments
    })), response(ANSWER)]
    asyncio.run(client.ask("Capacités de Noadkoko d'Alola après 20 et avant 40 dans Soleil et Lune"))
    journey.session.call_tool.assert_awaited_once_with("pokemon_level_up_moves", arguments=arguments)


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_empty_answer_is_an_error(journey, answer):
    journey.create.side_effect = [response(json.dumps(SELECTION)), response(answer)]
    with pytest.raises(ValueError, match="généré"):
        asyncio.run(client.ask(QUESTION))


def test_cli_reads_question_and_prints_answer(journey, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: f"  {QUESTION}  ")
    asyncio.run(client.main())
    assert capsys.readouterr().out == ANSWER + "\n"


def test_cli_empty_question_does_not_start_services(journey, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "  ")
    asyncio.run(client.main())
    assert journey.parameters == []
    journey.create.assert_not_called()


LIVE_CASES = [
    ("Quelles sont les évolutions de Pikachu ?", "pokemon_evolutions", {"pokemon": "pikachu"}),
    ("Quelles capacités Pikachu apprend-il par niveau entre les niveaux 10 et 20 dans Pokémon Rouge et Bleu ?",
     "pokemon_level_up_moves", {"pokemon": "pikachu", "min_level": 10, "max_level": 20, "version_group": "red-blue"}),
    ("Quelles CT ou CS Pikachu peut-il apprendre dans Pokémon Rouge et Bleu ?",
     "pokemon_machine_moves", {"pokemon": "pikachu", "version_group": "red-blue"}),
    ("Par quelles méthodes Pikachu apprend-il Tonnerre dans Pokémon Rouge et Bleu ?",
     "pokemon_move_learning_methods", {"pokemon": "pikachu", "version_group": "red-blue"}),
    (QUESTION, "pokemon_types", {"pokemon": "pikachu"}),
    ("Quels sont le numéro national et la génération d'introduction de Pikachu ?",
     "pokemon_pokedex_identity", {"pokemon": "pikachu"}),
    ("Quelles sont les capacités signature et pseudo-signature de Pikachu ?",
     "pokemon_signature_moves", {"pokemon": "pikachu"}),
    ("Décris le comportement de Pikachu dans la nature.", "pokemon_rag_search", {"pokemon": "pikachu"}),
    ("Comment fonctionne la reproduction des Pokémon ?", "pokemon_rag_search", {}),
    ("Quels sont les types de Noadkoko d'Alola ?", "pokemon_types", {}),
]


@pytest.mark.llm
@pytest.mark.real_data
@pytest.mark.models
@pytest.mark.long
@pytest.mark.parametrize("question, expected_tool, expected_arguments", LIVE_CASES,
                         ids=[f"{case[1]}-{i}" for i, case in enumerate(LIVE_CASES)])
def test_live_question_to_answer(question, expected_tool, expected_arguments, monkeypatch, record_property):
    """Vrai sous-processus MCP, vrais outils et vrai LLM ; aucun résultat simulé."""
    selected = []
    results = []
    original_choose = client.choose_tool
    original_extract = client.extract_result
    original_transport = client.stdio_client
    original_llm_factory = client.create_llm_client

    # Les modèles doivent déjà être en cache : aucun téléchargement pendant le test.
    # Le SDK stdio ne transmet pas toutes les variables du processus parent.
    def local_transport(parameters):
        parameters.env = {**(parameters.env or {}), "HF_HUB_OFFLINE": "1"}
        return original_transport(parameters)

    monkeypatch.setattr(client, "stdio_client", local_transport)
    monkeypatch.setattr(client, "ClientSession", partial(client.ClientSession, read_timeout_seconds=120))
    monkeypatch.setattr(client, "create_llm_client", lambda: original_llm_factory().with_options(
        timeout=90, max_retries=0
    ))

    def observe_choice(*args, **kwargs):
        choice = original_choose(*args, **kwargs)
        selected.append(choice)
        return choice

    def observe_result(result):
        extracted = original_extract(result)
        results.append(extracted)
        return extracted

    monkeypatch.setattr(client, "choose_tool", observe_choice)
    monkeypatch.setattr(client, "extract_result", observe_result)
    try:
        answer = asyncio.run(client.ask(question))
    finally:
        record_property("question", question)
        record_property("selection", json.dumps(selected, ensure_ascii=False))
        record_property("tool_result", json.dumps(results, ensure_ascii=False))
    record_property("answer", answer)
    assert len(selected) == 1
    assert len(results) == 1 and isinstance(results[0], dict)
    assert not results[0].get("error"), results[0]
    tool, arguments = selected[0]
    assert tool == expected_tool
    for key, expected in expected_arguments.items():
        actual = arguments.get(key)
        assert (actual.casefold() if isinstance(actual, str) else actual) == expected
    if expected_tool == "pokemon_move_learning_methods":
        assert arguments.get("move", "").casefold() in {"tonnerre", "thunderbolt"}
    if expected_tool == "pokemon_rag_search":
        assert arguments.get("question", "").strip()
        if not expected_arguments:
            assert arguments.get("pokemon") in (None, "")
        assert results[0]["results"], "La recherche réelle n'a retourné aucun passage"
        assert all(item["text"].strip() and item["source_file"] for item in results[0]["results"])
    else:
        collection = {
            "pokemon_evolutions": "evolutions",
            "pokemon_level_up_moves": "moves",
            "pokemon_machine_moves": "moves",
            "pokemon_move_learning_methods": "methods",
        }.get(expected_tool, "rows")
        rows = results[0][collection]
        assert results[0]["count"] == len(rows)
        assert rows, "Aucune donnée pour ce cas de référence"
    if "Alola" in question:
        assert "alola" in results[0]["pokemon"].casefold()
        row = results[0]["rows"][0]
        assert {row["type_1_fr"], row["type_2_fr"]} == {"Plante", "Dragon"}
    if expected_tool == "pokemon_pokedex_identity":
        assert results[0]["rows"][0]["national_number"] == 25
    assert answer.strip()
