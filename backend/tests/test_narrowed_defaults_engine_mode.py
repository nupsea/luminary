"""A cloud route chosen by the engine mode is not the host narrowing a model.

In Hybrid, `resolve("chat")` is the user's cloud model, and `narrowed_defaults`
reported it as the host overruling the local chat model. Settings then offered
to "switch" the local chat model to `gemini/...`, which the local installer
answered with 404.
"""

import pytest

from app.services import model_router, settings_service

LOCAL = "ollama/qwen3.5:4b"
VISION = "ollama/qwen3.5:4b"


@pytest.fixture
def routes(monkeypatch):
    def _apply(chat: str, background: str):
        per_role = {"chat": chat, "background": background, "vision": VISION}

        def fake_resolve(role, *, background=False):
            return model_router.ModelChoice(role, per_role[role], None, None)

        monkeypatch.setattr(model_router, "resolve", fake_resolve)
        monkeypatch.setattr(settings_service, "configured_chat_override", lambda: LOCAL)
        monkeypatch.setattr(settings_service, "configured_vision_override", lambda: VISION)

    return _apply


def test_hybrid_does_not_report_the_cloud_model_as_a_narrowing(routes):
    routes(chat="gemini/gemini-3.8-flash", background=LOCAL)
    assert model_router.narrowed_defaults() == {}


def test_cloud_mode_has_no_local_chat_route_to_report(routes):
    routes(chat="gemini/gemini-3.8-flash", background="gemini/gemini-3.8-flash")
    assert model_router.narrowed_defaults() == {}


def test_hybrid_still_reports_a_local_model_the_host_overruled(routes):
    routes(chat="gemini/gemini-3.8-flash", background="ollama/qwen3.5:2b")
    narrowed = model_router.narrowed_defaults()
    assert narrowed["chat"]["configured"] == LOCAL
    assert narrowed["chat"]["resolved"] == "ollama/qwen3.5:2b"
