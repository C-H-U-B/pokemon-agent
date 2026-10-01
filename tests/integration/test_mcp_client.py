"""Client integration with simulated MCP and LLM boundaries."""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
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
    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=Mock())
    monkeypatch.setattr(client, "stdio_client", transport)
    monkeypatch.setattr(client, "ClientSession", session_context)
    monkeypatch.setattr(client, "create_llm_client", lambda: llm)
    yield SimpleNamespace(session=session, create=create, tool=tool, parameters=parameters, close=llm.close)
    if events:
        assert events == ["transport_open", "session_open", "session_closed", "transport_closed"]
        llm.close.assert_called_once()


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
    questions = iter([f"  {QUESTION}  ", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(questions))
    asyncio.run(client.main())
    assert capsys.readouterr().out == ANSWER + "\n"


def test_cli_empty_question_does_not_start_services(journey, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "  ")
    asyncio.run(client.main())
    assert journey.parameters == []
    journey.create.assert_not_called()


def test_cli_reuses_server_and_catalog_for_two_questions(journey, monkeypatch, capsys):
    second = "Quels sont les types de Raichu ?"
    questions = iter([QUESTION, second, "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(questions))
    journey.create.side_effect = [
        response(json.dumps(SELECTION)), response(ANSWER),
        response(json.dumps({"tool": "pokemon_types", "arguments": {"pokemon": "Raichu"}})),
        response("Raichu est de type Électrik."),
    ]
    asyncio.run(client.main())
    assert len(journey.parameters) == 1
    journey.session.initialize.assert_awaited_once()
    journey.session.list_tools.assert_awaited_once()
    assert journey.session.call_tool.await_count == 2
    assert journey.session.call_tool.call_args.kwargs == {"arguments": {"pokemon": "Raichu"}}
    assert capsys.readouterr().out == ANSWER + "\nRaichu est de type Électrik.\n"
    prompt = journey.create.call_args_list[2].kwargs["messages"][1]["content"]
    assert second in prompt and QUESTION not in prompt


@pytest.mark.parametrize("ending", ["", "quit", " EXIT ", "/quit", EOFError(), KeyboardInterrupt()])
@pytest.mark.parametrize("after_answer", [False, True])
def test_cli_exit_closes_existing_session(journey, monkeypatch, ending, after_answer):
    inputs = iter(([QUESTION] if after_answer else []) + [ending])

    def read(_):
        value = next(inputs)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", read)
    asyncio.run(client.main())
    assert len(journey.parameters) == int(after_answer)
    assert journey.close.call_count == int(after_answer)


@pytest.mark.parametrize("error", [ConnectionError("MCP"), asyncio.CancelledError()])
def test_persistent_session_closes_on_second_call_failure(journey, error):
    journey.create.side_effect = [response(json.dumps(SELECTION)), response(ANSWER),
                                  response(json.dumps(SELECTION))]
    journey.session.call_tool.side_effect = [CallToolResult(content=[], structured_content=DATA), error]

    async def run():
        async with client.open_client() as conversation:
            assert await conversation.ask(QUESTION) == ANSWER
            await conversation.ask(QUESTION)

    with pytest.raises(type(error)):
        asyncio.run(run())
    assert len(journey.parameters) == 1
    assert journey.create.call_count == 3
