"""An installed model is used without the user re-selecting it.

A fresh 52 GB Mac defaulted to the 14B, the user pulled the 4B, and every Ask on Auto
still went to the absent 14B until the 4B was picked by hand.
"""

import pytest

import app.model_registry as registry
from app.services import components
from app.services import settings_service as svc


@pytest.fixture
def chat_default_14b(monkeypatch):
    saved = svc._cache["local_chat_model"]
    svc._cache["local_chat_model"] = ""
    monkeypatch.setattr(registry, "default_chat_model", lambda: "ollama/qwen2.5:14b-instruct")
    yield
    svc._cache["local_chat_model"] = saved


def _installed(monkeypatch, tags: set[str]) -> None:
    async def fake() -> set[str]:
        return tags

    monkeypatch.setattr(components, "_installed_ollama_models", fake)


async def test_an_absent_default_gives_way_to_the_installed_model(
    test_db, chat_default_14b, monkeypatch
):
    _installed(monkeypatch, {"qwen3.5:4b"})
    assert await components.adopt_installed_chat_model() == "ollama/qwen3.5:4b"
    assert svc.get_local_chat_model() == "ollama/qwen3.5:4b"


async def test_an_installed_chat_model_is_left_alone(test_db, chat_default_14b, monkeypatch):
    _installed(monkeypatch, {"qwen2.5:14b-instruct", "qwen3.5:4b"})
    assert await components.adopt_installed_chat_model() is None
    assert svc.get_local_chat_model() == "ollama/qwen2.5:14b-instruct"


async def test_nothing_installed_changes_nothing(test_db, chat_default_14b, monkeypatch):
    _installed(monkeypatch, set())
    assert await components.adopt_installed_chat_model() is None
