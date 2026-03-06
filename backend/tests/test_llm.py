"""Tests for LLMService and GET /settings/llm endpoint."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.services.llm import LLMService, get_llm_service

# ---------------------------------------------------------------------------
# Shared DB fixture for /settings/llm tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def settings_db(tmp_path, monkeypatch):
    """In-memory SQLite with tables; resets settings cache before/after."""
    import app.services.settings_service as svc_module
    from app.services.settings_service import _DEFAULTS

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory
    svc_module._cache.update(_DEFAULTS)

    yield

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    svc_module._cache.update(_DEFAULTS)
    await engine.dispose()

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
async def test_llm_settings_unavailable_when_ollama_down(settings_db):
    with patch("app.routers.settings._fetch_ollama_models", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_mode"] == "unavailable"
    assert data["available_local_models"] == []


@pytest.mark.asyncio
async def test_llm_settings_local_when_ollama_up(settings_db):
    with patch(
        "app.routers.settings._fetch_ollama_models",
        return_value=["ollama/llama3:latest", "ollama/mistral:latest"],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_mode"] == "local"
    assert "ollama/llama3:latest" in data["available_local_models"]
    assert "active_model" in data
    assert "cloud_providers" in data


@pytest.mark.asyncio
async def test_llm_settings_cloud_when_no_ollama_but_api_key(settings_db):
    """Cloud mode + openai key in DB → processing_mode=cloud, openai available."""
    from app.database import get_session_factory

    # Write cloud mode + encrypted openai key to the in-memory DB
    async with get_session_factory()() as session:
        from app.services.settings_service import update_llm_settings

        await update_llm_settings(
            session, mode="cloud", provider="openai", openai_api_key="sk-real-key"
        )

    with patch("app.routers.settings._fetch_ollama_models", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_mode"] == "cloud"
    openai_provider = next(p for p in data["cloud_providers"] if p["name"] == "openai")
    assert openai_provider["available"] is True


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
