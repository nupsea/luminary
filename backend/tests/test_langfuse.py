"""Tests for Langfuse integration in LLMService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.llm as llm_module
from app.services.llm import LLMService, _init_langfuse, _log_to_langfuse

# ---------------------------------------------------------------------------
# _init_langfuse
# ---------------------------------------------------------------------------


def test_init_langfuse_returns_none_when_keys_missing(monkeypatch):
    """No Langfuse client when keys are not configured."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    result = _init_langfuse()
    assert result is None
    get_settings.cache_clear()


def test_init_langfuse_creates_client_when_keys_set(monkeypatch):
    """Langfuse client is created when both keys are set."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    from app.config import get_settings

    get_settings.cache_clear()
    mock_langfuse_cls = MagicMock()
    mock_client = MagicMock()
    mock_langfuse_cls.return_value = mock_client

    with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_cls)}):
        result = _init_langfuse()

    assert result is mock_client
    mock_langfuse_cls.assert_called_once_with(public_key="pk-test", secret_key="sk-test")
    get_settings.cache_clear()


def test_init_langfuse_handles_import_error_gracefully(monkeypatch):
    """If Langfuse raises on init, function returns None without propagating."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    from app.config import get_settings

    get_settings.cache_clear()
    exploding_cls = MagicMock(side_effect=RuntimeError("boom"))
    with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=exploding_cls)}):
        result = _init_langfuse()

    assert result is None
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# _log_to_langfuse
# ---------------------------------------------------------------------------


def test_log_to_langfuse_noop_when_no_client(monkeypatch):
    """_log_to_langfuse is a no-op when get_langfuse returns None."""
    monkeypatch.setattr(llm_module, "get_langfuse", lambda: None)
    # Should not raise
    _log_to_langfuse("ollama/mistral", "hello", "world", 5, 3)


def test_log_to_langfuse_calls_start_generation(monkeypatch):
    """_log_to_langfuse calls start_generation and end on the Langfuse client."""
    mock_gen = MagicMock()
    mock_client = MagicMock()
    mock_client.start_generation.return_value = mock_gen
    monkeypatch.setattr(llm_module, "get_langfuse", lambda: mock_client)

    _log_to_langfuse("ollama/mistral", "my prompt", "my answer", 10, 20)

    mock_client.start_generation.assert_called_once()
    call_kwargs = mock_client.start_generation.call_args.kwargs
    assert call_kwargs["model"] == "ollama/mistral"
    assert call_kwargs["input"] == "my prompt"
    assert call_kwargs["output"] == "my answer"
    assert call_kwargs["usage"] == {"input": 10, "output": 20}
    mock_gen.end.assert_called_once()


def test_log_to_langfuse_truncates_prompt(monkeypatch):
    """Prompt is truncated to 2000 chars before logging."""
    mock_gen = MagicMock()
    mock_client = MagicMock()
    mock_client.start_generation.return_value = mock_gen
    monkeypatch.setattr(llm_module, "get_langfuse", lambda: mock_client)

    long_prompt = "x" * 5000
    _log_to_langfuse("ollama/mistral", long_prompt, "answer", 0, 0)

    call_kwargs = mock_client.start_generation.call_args.kwargs
    assert len(call_kwargs["input"]) == 2000


def test_log_to_langfuse_swallows_langfuse_errors(monkeypatch):
    """If start_generation raises, _log_to_langfuse does not propagate the error."""
    mock_client = MagicMock()
    mock_client.start_generation.side_effect = RuntimeError("network error")
    monkeypatch.setattr(llm_module, "get_langfuse", lambda: mock_client)

    # Should not raise
    _log_to_langfuse("ollama/mistral", "prompt", "completion", 0, 0)


# ---------------------------------------------------------------------------
# LLMService.generate — Langfuse is called on non-streaming completions
# ---------------------------------------------------------------------------


def _make_completion_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


@pytest.mark.asyncio
async def test_generate_calls_langfuse_observe_when_configured(monkeypatch):
    """LLMService.generate() logs to Langfuse when client is available."""
    mock_gen = MagicMock()
    mock_client = MagicMock()
    mock_client.start_generation.return_value = mock_gen
    monkeypatch.setattr(llm_module, "get_langfuse", lambda: mock_client)

    svc = LLMService()
    mock_response = _make_completion_response("result text")
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        await svc.generate("test prompt", model="ollama/mistral")

    # Assert langfuse observe (start_generation) was called
    mock_client.start_generation.assert_called_once()
    call_kwargs = mock_client.start_generation.call_args.kwargs
    assert "test prompt" in call_kwargs["input"]
    assert call_kwargs["output"] == "result text"


@pytest.mark.asyncio
async def test_generate_skips_langfuse_when_not_configured(monkeypatch):
    """LLMService.generate() does not call Langfuse when client is None."""
    monkeypatch.setattr(llm_module, "get_langfuse", lambda: None)

    svc = LLMService()
    mock_response = _make_completion_response("result")
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await svc.generate("prompt", model="ollama/mistral")

    assert result == "result"


# ---------------------------------------------------------------------------
# get_langfuse singleton
# ---------------------------------------------------------------------------


def test_get_langfuse_returns_none_by_default(monkeypatch):
    """get_langfuse() returns None when keys are not set."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    llm_module._langfuse = None  # reset singleton
    result = llm_module.get_langfuse()
    assert result is None
    llm_module._langfuse = None
    get_settings.cache_clear()
