"""Isolation des questions Web : ADK simulé, aucun appel au modèle."""

import asyncio
from types import SimpleNamespace

import pytest


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    from pokemon_rag.web import app
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
            history, state, _ = outputs[-1]
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
    assert "RuntimeError" in outputs[-1][0][-1]["content"]


def test_question_is_visible_before_answer_without_duplicate(web, monkeypatch):
    monkeypatch.setattr(web, "runner", FakeRunner())
    history = [{"role": "assistant", "content": "Ancienne réponse"}]

    async def run():
        return [output async for output in web.chat("  Pikachu ?  ", history, web.WebSession())]

    outputs = asyncio.run(run())
    assert outputs[0][0][:-1] == history + [{"role": "user", "content": "Pikachu ?"}]
    assert all(output[0][-1]["content"] == "…" for output in outputs[:-1])
    assert outputs[-1][0][-1]["content"] == "Réponse"
    assert len(outputs[-1][0]) == 3
    assert history == [{"role": "assistant", "content": "Ancienne réponse"}]


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
    assert "Préparation de la réponse · Qwen" not in waiting
    assert "Réponse reçue" in received
    assert "Préparation de la réponse · Qwen" in received
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
    assert "- Qwen : 3200 tokens lus, 200 générés · ≈ 14 tokens/s" in panel
    # Chaque mesure reste sous son propre appel.
    rag, sql = panel.split("### 1.2")
    assert "Recherche :" in rag and "Requête SQL" not in rag and "Requête SQL" in sql and "Recherche :" not in sql


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
