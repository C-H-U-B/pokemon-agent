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
