"""Every model failure names its cause and a step the user can take, never `ollama serve`
in the desktop app."""

import httpx
import litellm
import pytest

from app.exceptions import DependencyUnavailable
from app.services import llm_errors


def _connection(message: str) -> Exception:
    return litellm.APIConnectionError(message=message, llm_provider="ollama", model="ollama/x")


@pytest.fixture(autouse=True)
def _packaged(monkeypatch):
    monkeypatch.setattr(llm_errors, "is_packaged", lambda: True)
    monkeypatch.setattr(llm_errors, "_routes_locally", lambda: True)


def test_a_model_that_is_not_installed_offers_the_model_choice():
    exc = _connection('OllamaException - {"error":"model \'qwen2.5:14b-instruct\' not found"}')
    reason, text = llm_errors.describe(exc)
    assert reason == "model_missing"
    assert "qwen2.5:14b-instruct is not installed" in text


def test_a_timeout_says_the_first_answer_can_be_slow():
    exc = litellm.Timeout(message="timed out", model="ollama/x", llm_provider="ollama")
    assert llm_errors.describe(exc)[0] == "timeout"


def test_an_ollama_error_carries_ollama_s_own_reason():
    exc = _connection('OllamaException - {"error":"llama runner process has terminated"}')
    reason, text = llm_errors.describe(exc)
    assert reason == "model_error"
    assert "llama runner process has terminated" in text


def test_a_down_server_in_the_desktop_app_never_says_ollama_serve():
    exc = _connection("OllamaException - Cannot connect to host 127.0.0.1:49553")
    reason, text = llm_errors.describe(exc)
    assert reason == "server_down"
    assert "ollama serve" not in text and "reopen" in text


def test_a_source_install_may_still_be_told_to_start_ollama(monkeypatch):
    monkeypatch.setattr(llm_errors, "is_packaged", lambda: False)
    exc = _connection("OllamaException - Cannot connect")
    assert "ollama serve" in llm_errors.describe(exc)[1]


def test_a_host_refusal_keeps_its_own_message():
    assert llm_errors.describe(DependencyUnavailable("This Mac cannot run it."))[1] == (
        "This Mac cannot run it."
    )


def test_a_cloud_outage_is_not_blamed_on_the_local_server(monkeypatch):
    monkeypatch.setattr(llm_errors, "_routes_locally", lambda: False)
    exc = litellm.APIConnectionError(
        message="Connection error",
        llm_provider="openai",
        model="openai/gpt",
        request=httpx.Request("POST", "https://api.openai.com"),
    )
    assert llm_errors.describe(exc)[0] == "provider_down"
