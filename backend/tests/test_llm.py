"""Tests for LLMService and GET /settings/llm endpoint."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.llm import LLMService, get_llm_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completion_response(content: str) -> MagicMock:
    """Build a fake litellm completion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_stream_chunk(content: str | None) -> MagicMock:
    """Build a fake streaming chunk."""
    delta = MagicMock()
    delta.content = content
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


async def _async_iter(items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# LLMService.generate — non-streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_non_stream_returns_string():
    svc = LLMService()
    mock_response = _make_completion_response("Hello world")
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await svc.generate("Say hello")
    assert result == "Hello world"
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_generate_non_stream_uses_system_message():
    svc = LLMService()
    mock_response = _make_completion_response("ok")
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock_ac:
        await svc.generate("prompt", system="Be concise")
    call_kwargs = mock_ac.call_args.kwargs
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Be concise"
    assert messages[1]["role"] == "user"


@pytest.mark.asyncio
async def test_generate_non_stream_empty_system_omits_system_message():
    svc = LLMService()
    mock_response = _make_completion_response("ok")
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock_ac:
        await svc.generate("prompt")
    call_kwargs = mock_ac.call_args.kwargs
    messages = call_kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


# ---------------------------------------------------------------------------
# LLMService.generate — streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_returns_async_generator():
    svc = LLMService()
    chunks = [
        _make_stream_chunk("Hello"),
        _make_stream_chunk(" world"),
        _make_stream_chunk(None),  # None content should be skipped
    ]

    async def fake_acompletion(**kwargs):  # noqa: ARG001
        return _async_iter(chunks)

    # Patch must remain active while iterating (generator executes lazily)
    with patch("litellm.acompletion", side_effect=fake_acompletion):
        result = await svc.generate("prompt", stream=True)
        assert isinstance(result, AsyncGenerator)
        tokens = [t async for t in result]
    assert tokens == ["Hello", " world"]


@pytest.mark.asyncio
async def test_generate_stream_yields_strings():
    svc = LLMService()
    chunks = [_make_stream_chunk("tok1"), _make_stream_chunk("tok2")]

    async def fake_acompletion(**kwargs):  # noqa: ARG001
        return _async_iter(chunks)

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        gen = await svc.generate("x", stream=True)
        tokens = [t async for t in gen]
    assert all(isinstance(t, str) for t in tokens)


# ---------------------------------------------------------------------------
# Model routing — api_base / api_key forwarded correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_prefix_sets_api_base(monkeypatch):
    monkeypatch.setenv("LITELLM_DEFAULT_MODEL", "ollama/mistral")
    monkeypatch.setenv("OLLAMA_URL", "http://custom-ollama:11434")
    from app.config import get_settings

    get_settings.cache_clear()
    svc = LLMService()
    mock_response = _make_completion_response("ok")
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock_ac:
        await svc.generate("hi", model="ollama/llama3")
    kwargs = mock_ac.call_args.kwargs
    assert kwargs["api_base"] == "http://custom-ollama:11434"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_openai_prefix_sets_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
    from app.config import get_settings

    get_settings.cache_clear()
    svc = LLMService()
    mock_response = _make_completion_response("ok")
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock_ac:
        await svc.generate("hi", model="openai/gpt-4o")
    kwargs = mock_ac.call_args.kwargs
    assert kwargs["api_key"] == "sk-test123"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_anthropic_prefix_sets_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key-xyz")
    from app.config import get_settings

    get_settings.cache_clear()
    svc = LLMService()
    mock_response = _make_completion_response("ok")
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock_ac:
        await svc.generate("hi", model="anthropic/claude-3-haiku")
    kwargs = mock_ac.call_args.kwargs
    assert kwargs["api_key"] == "ant-key-xyz"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gemini_prefix_sets_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-key-abc")
    from app.config import get_settings

    get_settings.cache_clear()
    svc = LLMService()
    mock_response = _make_completion_response("ok")
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock_ac:
        await svc.generate("hi", model="gemini/gemini-2.0-flash")
    kwargs = mock_ac.call_args.kwargs
    assert kwargs["api_key"] == "goog-key-abc"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GET /settings/llm endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_settings_unavailable_when_ollama_down(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    with patch("app.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client_cls.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_mode"] == "unavailable"
    assert data["available_local_models"] == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_llm_settings_local_when_ollama_up(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    from app.config import get_settings

    get_settings.cache_clear()

    fake_tags_response = MagicMock()
    fake_tags_response.status_code = 200
    fake_tags_response.json.return_value = {
        "models": [{"name": "llama3:latest"}, {"name": "mistral:latest"}]
    }

    with patch("app.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=fake_tags_response)
        mock_client_cls.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_mode"] == "local"
    assert "ollama/llama3:latest" in data["available_local_models"]
    assert "active_model" in data
    assert "cloud_providers" in data
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_llm_settings_cloud_when_no_ollama_but_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    with patch("app.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=Exception("Ollama down"))
        mock_client_cls.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_mode"] == "cloud"
    openai_provider = next(p for p in data["cloud_providers"] if p["name"] == "openai")
    assert openai_provider["available"] is True
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_llm_service_returns_same_instance():
    import app.services.llm as llm_module

    llm_module._llm_service = None  # reset
    svc1 = get_llm_service()
    svc2 = get_llm_service()
    assert svc1 is svc2
    llm_module._llm_service = None  # cleanup
