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
