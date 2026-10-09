"""Isolation des questions Web : ADK simulé, aucun appel au modèle."""

import asyncio
from types import SimpleNamespace

import pytest


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    from pokemon_rag.web import app
    # Les questions simulées ne doivent pas s'ajouter aux traces réelles du projet.
    monkeypatch.setattr(app, "WEB_TRACE_FILE", tmp_path / "web_traces.jsonl")
    # Catalogue d'images vide : ces tests ne portent pas sur les illustrations et n'ouvrent pas la base.
    monkeypatch.setattr(app, "pokemon_image_urls", lambda: {})
    return app


class FakeRunner:
    app_name = "test"

    def __init__(self, fail=False):
        self.session_service = self
        self.created = []
        self.deleted = []
        self.messages = []
        self.fail = fail

    async def create_session(self, **kwargs):
        session_id = str(len(self.created) + 1)
        self.created.append(session_id)
        return SimpleNamespace(id=session_id)

    async def delete_session(self, session_id, **kwargs):
        self.deleted.append(session_id)

    async def run_async(self, session_id, new_message, **kwargs):
        self.messages.append((session_id, new_message.parts[0].text))
        if self.fail:
            raise RuntimeError("outil indisponible")
        yield SimpleNamespace(
            content=SimpleNamespace(parts=[SimpleNamespace(text="Réponse", function_call=None, function_response=None)]),
            is_final_response=lambda: True,
        )


def test_questions_use_distinct_sessions_and_keep_display_history(web, monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(web, "runner", fake)

    async def run():
        history = []
        state = web.WebSession()
        for message in ("Palmaval ?", "Cocotine ?"):
            outputs = [output async for output in web.chat(message, history, state)]
            history = outputs[-1][0]
        return history

    history = asyncio.run(run())
    assert fake.messages == [("1", "Palmaval ?"), ("2", "Cocotine ?")]
    assert fake.deleted == fake.created == ["1", "2"]
    assert [item["content"] for item in history] == ["Palmaval ?", "Réponse", "Cocotine ?", "Réponse"]


def test_failed_request_deletes_session_and_finishes(web, monkeypatch):
    fake = FakeRunner(fail=True)
    monkeypatch.setattr(web, "runner", fake)

    async def run():
        return [output async for output in web.chat("Question", [], web.WebSession())]

    outputs = asyncio.run(run())
    assert fake.deleted == ["1"]
    # Page publique : ni le type ni le texte de l'exception, dans la réponse comme dans le panneau.
    assert outputs[-1][0][-1]["content"] == web.TECHNICAL_ERROR_MESSAGE
    assert "RuntimeError" not in outputs[-1][2] and "outil indisponible" not in outputs[-1][2]


def test_abandoned_question_stops_the_agent_and_deletes_its_session(web, monkeypatch):
    # Gradio ferme le générateur quand la page est fermée ou la conversation réinitialisée.
    class SlowRunner(FakeRunner):
        cancelled = False

        async def run_async(self, session_id, new_message, **kwargs):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            yield

    fake = SlowRunner()
    monkeypatch.setattr(web, "runner", fake)
    monkeypatch.setattr(web, "REFRESH_INTERVAL", 0.01)

    async def run():
        outputs = web.chat("Question", [], web.WebSession())
        await outputs.__anext__()
        await outputs.__anext__()  # un rafraîchissement : l'agent a démarré
        await outputs.aclose()
        await asyncio.sleep(0.05)
        # Lu avant la fin de asyncio.run, qui annule de toute façon les tâches restantes.
        return fake.cancelled, list(fake.deleted)

    assert asyncio.run(run()) == (True, ["1"])


def test_question_is_visible_before_answer_without_duplicate(web, monkeypatch):
    monkeypatch.setattr(web, "runner", FakeRunner())
    history = [{"role": "assistant", "content": "Ancienne réponse"}]

    async def run():
        return [output async for output in web.chat("  Pikachu ?  ", history, web.WebSession())]

    outputs = asyncio.run(run())
    assert outputs[0][0][:-1] == history + [{"role": "user", "content": "Pikachu ?"}]
    assert outputs[0][0][-1]["content"] == web.PENDING_ANSWER
    # Les rafraîchissements du chrono ne renvoient ni la conversation (le navigateur redescendrait en bas
    # dix fois par seconde) ni l'état (une suggestion choisie pendant l'attente serait écrasée).
    skip = web.gr.skip()
    assert all(output[0] == skip for output in outputs[1:-1]) and all(output[1] == skip for output in outputs)
    assert outputs[-1][0][-1]["content"] == "Réponse"
    assert len(outputs[-1][0]) == 3
    assert history == [{"role": "assistant", "content": "Ancienne réponse"}]


def test_the_graph_receives_the_path_at_the_start_and_at_the_end_not_at_every_refresh(web, monkeypatch):
    import json

    class SlowRunner(FakeRunner):
        async def run_async(self, session_id, new_message, **kwargs):
            await asyncio.sleep(0.05)  # plusieurs rafraîchissements du chrono sans événement
            async for event in super().run_async(session_id, new_message, **kwargs):
                yield event

    monkeypatch.setattr(web, "runner", SlowRunner())
    monkeypatch.setattr(web, "REFRESH_INTERVAL", 0.01)
    state = web.WebSession()

    async def run(message):
        return [output[3] async for output in web.chat(message, [], state)]

    sent = asyncio.run(run("Pikachu ?"))
    first, last = json.loads(sent[0]), json.loads(sent[-1])
    assert [step[1] for step in first["path"]] == ["question", "choix"] and first["running"] is True
    assert first["user_icon"].startswith("https://www.pokepedia.fr/images/")
    assert len(sent) > 3 and all(value == web.gr.skip() for value in sent[1:-1])
    # Réponse du modèle simulé sans aucun outil : non vérifiée, donc vers le rejet ; même question, même identifiant.
    assert [step[1] for step in last["path"]] == ["question", "choix", "rejet"] and last["running"] is False
    assert last["id"] == first["id"] and last["user_icon"] == first["user_icon"]
    too_long = json.loads(asyncio.run(run("x" * (web.MAX_QUESTION_CHARS + 1)))[-1])
    assert [step[:2] for step in too_long["path"]][-1] == ["question", "rejet"] and too_long["id"] != first["id"]


def test_the_opening_graph_replays_the_recorded_example_without_any_model_call(web):
    import json
    opening = json.loads(web._opening_graph())
    assert [step[1] for step in opening["path"]] == [
        "question", "choix", "guard", "mcp", "base", "budget", "redige", "reponse"]
    assert opening["path"][0][2] == web.FIRST_QUESTION and opening["running"] is False


def test_overlong_question_is_refused_before_any_model_call(web, monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(web, "runner", fake)

    async def run(message):
        return [output async for output in web.chat(message, [], web.WebSession())]

    outputs = asyncio.run(run("a" * (web.MAX_QUESTION_CHARS + 1)))
    assert outputs[-1][0][-1]["content"] == web.QUESTION_TOO_LONG and fake.messages == []
    asyncio.run(run("a" * web.MAX_QUESTION_CHARS))
    assert len(fake.messages) == 1


def test_first_documentary_search_warns_that_the_base_may_still_be_loading(web, monkeypatch):
    def event(call=None, response=None):
        return SimpleNamespace(is_final_response=lambda: False, content=SimpleNamespace(parts=[SimpleNamespace(
            text=None, function_call=call and SimpleNamespace(name=call, args={}),
            function_response=response and SimpleNamespace(name=response, response={}))]))

    class SearchRunner(FakeRunner):
        async def run_async(self, session_id, new_message, **kwargs):
            yield event(call="pokemon_rag_search")
            await asyncio.sleep(0.05)
            yield event(response="pokemon_rag_search")

    monkeypatch.setattr(web, "runner", SearchRunner())
    monkeypatch.setattr(web, "REFRESH_INTERVAL", 0.01)
    monkeypatch.setattr(web, "_documentary_base_ready", False)

    async def run():
        return [output[2] async for output in web.chat("Décris Ronflex", [], web.WebSession())]

    assert any("peut encore se charger" in panel for panel in asyncio.run(run()))
    assert web._documentary_base_ready
    assert not any("peut encore se charger" in panel for panel in asyncio.run(run()))


def test_missing_final_response_is_not_reported_as_success(web, monkeypatch):
    class EmptyRunner(FakeRunner):
        async def run_async(self, **kwargs):
            if False:
                yield

    monkeypatch.setattr(web, "runner", EmptyRunner())

    async def run():
        return [output async for output in web.chat("Pikachu ?", [], web.WebSession())]

    outputs = asyncio.run(run())
    assert "Aucune réponse finale" in outputs[-1][2]
    assert "Réponse disponible" not in outputs[-1][2]


def test_model_sees_the_wiki_page_instead_of_the_local_file_name():
    from pokemon_rag.agent.context_budget import bounded_tool_result
    passages = {"question": "Que fait Ronflex ?", "pokemon": "Ronflex", "results": [
        {"text": "Ronflex dort.", "pokemon": "Ronflex", "source_file": "0143_ronflex.md", "section_path": "Descriptions"}]}
    row = bounded_tool_result(passages, question="Que fait Ronflex ?")["results"][0]
    assert row["source"] == "Poképédia, page Ronflex" and "source_file" not in row
    assert passages["results"][0]["source_file"] == "0143_ronflex.md"   # la réponse MCP n'est pas modifiée


def test_repeated_tool_calls_distinguish_received_and_pending(web):
    activity = web._format_activity(
        [("pokemon_types", {"pokemon": "Pikachu"}), ("pokemon_types", {"pokemon": "Raichu"})],
        ["pokemon_types"], 2.0, "Exécution",
    )
    assert activity.count("Réponse reçue") == 1
    assert activity.count("réponse en attente") == 1
    assert "2 appel(s) d'outil" in activity


def test_timing_counts_parallel_tools_once_and_accumulates_retries(web):
    timing = web.ActivityTiming()
    timing.observe([("pokemon_types", {}), ("pokemon_rag_search", {})], [], 2.0)
    timing.observe([], ["pokemon_types"], 3.0)
    assert timing.phase == "tools"
    timing.observe([], ["pokemon_rag_search"], 5.0)
    timing.observe([("pokemon_types", {})], [], 7.0)
    timing.observe([], ["pokemon_types"], 8.0)
    timing.transition("finished", 10.0)
    assert timing.duration("analysis", 20.0) == 2.0
    assert timing.duration("tools", 20.0) == 4.0
    assert timing.duration("generation", 20.0) == 4.0
    assert timing.calls == [
        ("pokemon_types", 2.0, 3.0), ("pokemon_rag_search", 2.0, 5.0),
        ("pokemon_types", 7.0, 8.0),
    ]


def test_pending_tool_timer_is_frozen_when_request_finishes(web):
    timing = web.ActivityTiming()
    timing.observe([("pokemon_types", {})], [], 1.0)
    timing.transition("finished", 4.0)
    panel = web._format_activity([("pokemon_types", {})], [], 9.0, "Erreur", timing)
    assert "**⏱ 3.0 s** · en attente" in panel


@pytest.mark.parametrize("tool, technology, description", [
    ("pokemon_types", "base SQLite", "Consultation des données Pokémon"),
    ("pokemon_rag_search", "Poképédia / index Chroma", "Recherche de passages textuels"),
])
def test_activity_explains_requested_backend_and_response_preparation(web, tool, technology, description):
    waiting = web._format_activity([(tool, {})], [], 1.0, "Recherche en cours")
    received = web._format_activity([(tool, {})], [tool], 2.0, "Retour reçu")
    assert technology in waiting
    assert description in waiting
    assert f"Préparation de la réponse · {web.MODEL_LABEL}" not in waiting
    assert "Réponse reçue" in received
    assert f"Préparation de la réponse · {web.MODEL_LABEL}" in received
    assert "passages textuels" not in waiting if tool == "pokemon_types" else "base SQLite" not in waiting


STARTUP = {"embedding": 18.2, "reranker": 17.5, "corpus": 17.7, "bm25": 0.8, "total": 54.3}
SEARCH = {"vector": 0.05, "bm25": 0.02, "rrf": 0.001, "reranker": 1.1, "total": 1.23}


def tool_event(*names, measures=(), usage=None):
    """Événement ADK réduit à ce que lit le panneau : retours d'outils, état et usage."""
    return SimpleNamespace(actions=SimpleNamespace(state_delta={"tool_timings": list(measures)} if measures else {}),
                           usage_metadata=usage)


def test_panel_shows_database_loading_search_steps_sql_time_and_tokens(web):
    timing = web.ActivityTiming()
    usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=40)
    timing.observe([("pokemon_rag_search", {}), ("pokemon_types", {})], [], 4.0, tool_event(usage=usage))
    measures = [{"tool": "pokemon_rag_search", "timings": {**SEARCH, "startup": STARTUP}, "passages": 5},
                {"tool": "pokemon_types", "execution_time": 0.048}]
    timing.observe([], ["pokemon_rag_search", "pokemon_types"], 60.0, tool_event(measures=measures))
    usage = SimpleNamespace(prompt_token_count=2000, candidates_token_count=160)
    timing.observe([], [], 70.0, tool_event(measures=measures, usage=usage))
    timing.transition("finished", 70.0)
    panel = web._format_activity([("pokemon_rag_search", {}), ("pokemon_types", {})],
                                 ["pokemon_rag_search", "pokemon_types"], 70.0, "Réponse disponible", timing)
    # Le chargement est explicite dans le résumé et détaillé sous l'appel.
    assert "- Chargement de la base documentaire (premier appel) : 54.3 s" in panel
    assert ("- Chargement de la base (premier appel) : 54.3 s (modèle d'embedding 18.20 s · "
            "modèle de reclassement 17.50 s · corpus 17.70 s · index lexical 0.80 s)") in panel
    assert ("- Recherche : 1.23 s (vectorielle 0.05 s · lexicale 0.02 s · fusion 0.00 s · "
            "reclassement 1.10 s) · 5 passage(s)") in panel
    assert "- Requête SQL : 48 ms" in panel
    # Analyse 4 s + préparation 10 s = 14 s de modèle pour 200 tokens générés.
    assert f"- {web.MODEL_LABEL} : 3200 tokens lus, 200 générés · ≈ 14 tokens/s, lecture des requêtes comprise" in panel
    # Chaque mesure reste sous son propre appel.
    rag, sql = panel.split("### 1.2")
    assert "Recherche :" in rag and "Requête SQL" not in rag and "Requête SQL" in sql and "Recherche :" not in sql


def test_trace_counts_thinking_tokens_and_flags_an_answer_cut_by_the_output_limit(web):
    # Sous Gemini, la réflexion consomme la limite de sortie : la réponse visible peut être coupée bien avant.
    timing = web.ActivityTiming()
    usage = SimpleNamespace(prompt_token_count=4000, candidates_token_count=456, thoughts_token_count=568)
    event = tool_event(usage=usage)
    event.finish_reason = web.types.FinishReason.MAX_TOKENS
    timing.observe([], [], 1.0, event)
    trace = web._web_trace("Question", "Réponse cou", "answered", None, [], timing, 2.0)
    assert trace["tokens"] == {"prompt": 4000, "output": 456, "thinking": 568, "output_limit_reached": True}
    assert web._web_trace("Q", "R", "answered", None, [], web.ActivityTiming(), 1.0)["tokens"] == {
        "prompt": 0, "output": 0, "thinking": 0, "output_limit_reached": False}


def test_warm_search_shows_no_loading_and_an_empty_search_shows_zero_passages(web):
    timing = web.ActivityTiming()
    timing.observe([("pokemon_rag_search", {})], [], 1.0)
    timing.observe([], ["pokemon_rag_search"], 1.2, tool_event(
        measures=[{"tool": "pokemon_rag_search", "timings": {"total": 0.2}, "passages": 0}]))
    panel = web._format_activity([("pokemon_rag_search", {})], ["pokemon_rag_search"], 2.0, "Retour reçu", timing)
    assert "Chargement de la base" not in panel
    assert "- Recherche : 0.20 s · 0 passage(s)" in panel


def test_measure_follows_its_own_call_when_an_earlier_same_named_call_has_none(web):
    # Un appel refusé par le guard revient sans mesure ; celle du suivant ne doit pas lui être attribuée.
    timing = web.ActivityTiming()
    timing.observe([("pokemon_types", {})], [], 1.0)
    timing.observe([], ["pokemon_types"], 1.1, tool_event())
    timing.observe([("pokemon_types", {})], [], 2.0)
    timing.observe([], ["pokemon_types"], 2.1, tool_event(measures=[{"tool": "pokemon_types", "execution_time": 0.01}]))
    assert timing.measures == {1: {"tool": "pokemon_types", "execution_time": 0.01}}
    panel = web._format_activity([("pokemon_types", {}), ("pokemon_types", {})], ["pokemon_types"] * 2, 3.0, "ok", timing)
    refused, executed = panel.split("### 1.2")
    assert "Requête SQL" not in refused and "- Requête SQL : 10 ms" in executed


def test_panel_without_measures_or_usage_is_unchanged(web):
    timing = web.ActivityTiming()
    timing.observe([("pokemon_types", {})], [], 1.0)
    timing.observe([], ["pokemon_types"], 2.0)
    panel = web._format_activity([("pokemon_types", {})], ["pokemon_types"], 3.0, "ok", timing)
    assert "Requête SQL" not in panel and "tokens" not in panel and "Chargement" not in panel


def test_warm_up_starts_the_tool_server_and_never_breaks_the_page(web, monkeypatch, caplog):
    calls = []

    async def listed():
        calls.append("get_tools")
        return []

    async def unavailable():
        raise RuntimeError("serveur MCP indisponible")

    monkeypatch.setattr(web, "pokemon_mcp", SimpleNamespace(get_tools=listed))
    asyncio.run(web._warm_up())
    assert calls == ["get_tools"]
    monkeypatch.setattr(web, "pokemon_mcp", SimpleNamespace(get_tools=unavailable))
    with caplog.at_level("WARNING", logger="pokemon_rag.web.app"):
        asyncio.run(web._warm_up())
    assert "warm_up_failed" in caplog.text


def read_traces(web):
    import json
    return [json.loads(line) for line in web.WEB_TRACE_FILE.read_text(encoding="utf-8").splitlines()]


def test_each_question_appends_one_trace_with_its_answer_and_outcome(web, monkeypatch):
    monkeypatch.setattr(web, "runner", FakeRunner())

    async def run():
        for message in ("Palmaval ?", "Cocotine ?"):
            [output async for output in web.chat(message, [], web.WebSession())]

    asyncio.run(run())
    first, second = read_traces(web)
    assert (first["question"], first["answer"], first["outcome"]) == ("Palmaval ?", "Réponse", "answered")
    assert second["question"] == "Cocotine ?" and first["trace_id"] != second["trace_id"]
    assert first["model"] == web.LLM_MODEL and first["server"] == web.LLM_BASE_URL
    assert first["tools"] == [] and first["error"] is None and first["seconds"]["total"] >= 0


def test_failed_and_empty_requests_are_traced_as_such(web, monkeypatch):
    class EmptyRunner(FakeRunner):
        async def run_async(self, session_id, new_message, **kwargs):
            yield SimpleNamespace(content=None, is_final_response=lambda: True)

    async def run(runner):
        monkeypatch.setattr(web, "runner", runner)
        [output async for output in web.chat("Question", [], web.WebSession())]

    asyncio.run(run(FakeRunner(fail=True)))
    asyncio.run(run(EmptyRunner()))
    failed, empty = read_traces(web)
    assert failed["outcome"] == "error" and failed["error"] == "RuntimeError: outil indisponible"
    assert empty["outcome"] == "no_final_response" and empty["error"] is None


def test_trace_keeps_tool_arguments_measures_results_and_names_abstentions(web):
    timing = web.ActivityTiming()
    calls = [("pokemon_level_up_moves", {"pokemon": "Carabaffe", "min_level": 10}), ("pokemon_types", {"pokemon": "Carabaffe"})]
    refusal = {"error": "invalid_explicit_constraints", "required_arguments": {"max_level": 30}}
    types_result = {"operation": "get_pokemon_types", "rows": [{"name_fr": "Carabaffe", "type_1_fr": "Eau"}]}

    def returned(name, response, measures=()):
        event = tool_event(measures=measures)
        event.content = SimpleNamespace(parts=[SimpleNamespace(
            function_response=SimpleNamespace(name=name, response=response))])
        return event

    timing.observe(calls[:1], [], 1.0)
    timing.observe([], ["pokemon_level_up_moves"], 1.5, returned("pokemon_level_up_moves", refusal))
    timing.observe(calls[1:], [], 3.0)
    timing.observe([], ["pokemon_types"], 3.25, returned(
        "pokemon_types", types_result, [{"tool": "pokemon_types", "execution_time": 0.04}]))
    timing.transition("finished", 9.0)
    trace = web._web_trace("Question", "Carabaffe est de type Eau.", "answered", None, calls, timing, 9.0)
    assert trace["tools"] == [
        {"name": "pokemon_level_up_moves", "arguments": calls[0][1], "start": 1.0, "seconds": 0.5, "result": refusal},
        {"name": "pokemon_types", "arguments": calls[1][1], "start": 3.0, "seconds": 0.25, "execution_time": 0.04, "result": types_result},
    ]
    assert trace["seconds"] == {"total": 9.0, "analysis": 1.0, "tools": 0.75, "generation": 7.25}
    for text, outcome in ((web.TOOL_FAILURE_ABSTENTION, "tool_failure_abstention"),
                          (web.BUDGET_ABSTENTION, "budget_abstention")):
        assert web._web_trace("Question", text, "answered", None, [], web.ActivityTiming(), 1.0)["outcome"] == outcome


def test_trace_goes_to_standard_output_only_when_the_host_has_no_persistent_disk(web, monkeypatch, capsys):
    import json
    trace = web._web_trace("Palmaval ?", "Réponse", "answered", None, [], web.ActivityTiming(), 1.0)
    web._save_web_trace(trace)
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("WEB_TRACE_STDOUT", "1")
    web._save_web_trace(trace)
    line = json.loads(capsys.readouterr().out)
    assert line["message"] == "Palmaval ?" and line["web_trace"]["answer"] == "Réponse"
    assert len(read_traces(web)) == 2


def test_unwritable_trace_never_breaks_an_answer(web, monkeypatch, tmp_path, caplog):
    # Le chemin de trace est un dossier : l'écriture échoue, la réponse doit rester affichée.
    monkeypatch.setattr(web, "WEB_TRACE_FILE", tmp_path)
    monkeypatch.setattr(web, "runner", FakeRunner())

    async def run():
        return [output async for output in web.chat("Palmaval ?", [], web.WebSession())]

    with caplog.at_level("WARNING", logger="pokemon_rag.web.app"):
        outputs = asyncio.run(run())
    assert outputs[-1][0][-1]["content"] == "Réponse" and "web_trace_failed" in caplog.text
