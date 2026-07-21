"""With no internet, routed cloud calls must fall back to the local model.

The app is local-first: losing connectivity should degrade to Ollama rather than
surface an error. Explicitly pinned models are exempt so evals and per-request
overrides stay reproducible.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from app.services import connectivity
from app.services import settings_service as ss
from app.services.llm import LLMService, _is_offline_error


@pytest.fixture(autouse=True)
def _online(monkeypatch):
    """Default to 'provider reachable' so tests exercise the reactive path unless
    they opt into the proactive offline reroute."""
    connectivity.reset_cache()
    monkeypatch.setattr(connectivity, "provider_reachable", lambda model: True)
    yield
    connectivity.reset_cache()


def _connection_error() -> Exception:
    """The exception litellm actually raises offline: InternalServerError whose
    cause chain is a connection failure, NOT APIConnectionError."""
    import litellm

    root = ConnectionError("Cannot connect to host api.openai.com:443")
    try:
        raise litellm.InternalServerError(
            message="OpenAIException - Connection error",
            llm_provider="openai",
            model="gpt-5-mini",
        ) from root
    except litellm.InternalServerError as exc:
        return exc


class TestOfflineErrorDetection:
    def test_litellm_internal_server_error_from_connection_is_offline(self):
        assert _is_offline_error(_connection_error())

    def test_plain_value_error_is_not_offline(self):
        assert not _is_offline_error(ValueError("bad json"))

    def test_genuine_internal_server_error_is_not_offline(self):
        import litellm

        exc = litellm.InternalServerError(
            message="upstream 500", llm_provider="openai", model="gpt-5-mini"
        )
        assert not _is_offline_error(exc)


def _response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = None
    return response


@pytest.fixture
def cloud_routing():
    """Route to a cloud provider, as hybrid mode does for interactive calls."""
    original = dict(ss._cache)
    ss._cache.update(
        {
            "llm_mode": "cloud",
            "cloud_provider": "openai",
            "cloud_model": "gpt-5-mini",
            "openai_api_key": "sk-test-not-a-real-key",
        }
    )
    yield
    ss._cache.clear()
    ss._cache.update(original)


def _unreachable_then_ok(text: str = "local answer"):
    """First call fails with the exception litellm really raises offline; retry ok."""
    calls: list[dict] = []

    async def side_effect(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise _connection_error()
        return _response(text)

    return side_effect, calls


@pytest.mark.asyncio
async def test_routed_cloud_call_falls_back_to_local(cloud_routing):
    svc = LLMService()
    side_effect, calls = _unreachable_then_ok()
    with patch("litellm.acompletion", side_effect=side_effect):
        result = await svc.complete([{"role": "user", "content": "hi"}])

    assert result == "local answer"
    assert len(calls) == 2
    assert calls[0]["model"].startswith("openai/")
    assert calls[1]["model"].startswith("ollama/"), "retry must use the local model"


@pytest.mark.asyncio
async def test_offline_reroutes_before_any_cloud_call(cloud_routing, monkeypatch):
    """When the probe says offline, no cloud call is attempted at all."""
    monkeypatch.setattr(connectivity, "provider_reachable", lambda model: False)
    svc = LLMService()
    calls: list[dict] = []

    async def side_effect(**kwargs):
        calls.append(kwargs)
        return _response("local answer")

    with patch("litellm.acompletion", side_effect=side_effect):
        result = await svc.complete([{"role": "user", "content": "hi"}])

    assert result == "local answer"
    assert len(calls) == 1, "must not attempt the cloud call first"
    assert calls[0]["model"].startswith("ollama/")


@pytest.mark.asyncio
async def test_pinned_model_does_not_fall_back(cloud_routing):
    """An explicit model= is a reproducibility contract -- never silently swapped."""
    svc = LLMService()
    side_effect, calls = _unreachable_then_ok()
    with (
        patch("litellm.acompletion", side_effect=side_effect),
        pytest.raises(litellm.InternalServerError),
    ):
        await svc.complete([{"role": "user", "content": "hi"}], model="openai/gpt-5-mini")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_local_call_does_not_fall_back(cloud_routing):
    """Ollama being down is a real failure; there is nowhere further to go."""
    svc = LLMService()
    side_effect, calls = _unreachable_then_ok()
    with (
        patch("litellm.acompletion", side_effect=side_effect),
        pytest.raises(litellm.InternalServerError),
    ):
        await svc.complete([{"role": "user", "content": "hi"}], model="ollama/qwen2.5:14b-instruct")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_auth_error_is_not_masked_by_fallback(cloud_routing):
    """A bad key must surface, not be hidden behind a local answer."""
    svc = LLMService()

    async def side_effect(**kwargs):
        raise litellm.AuthenticationError(
            message="bad key", llm_provider="openai", model="gpt-5-mini"
        )

    with (
        patch("litellm.acompletion", side_effect=side_effect),
        pytest.raises(litellm.AuthenticationError),
    ):
        await svc.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_hybrid_background_call_is_already_local(cloud_routing):
    """Regression guard for the privacy routing: in hybrid, background is local."""
    ss._cache["llm_mode"] = "hybrid"
    svc = LLMService()
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=_response("ok")
    ) as mock_ac:
        await svc.complete([{"role": "user", "content": "hi"}], background=True)
    assert mock_ac.call_args.kwargs["model"].startswith("ollama/")


@pytest.mark.asyncio
async def test_cloud_mode_ignores_background(cloud_routing):
    """Documents a real gap: `background=True` only routes local in HYBRID mode.

    In cloud mode get_effective_routing returns the cloud model regardless, so the
    local-only call sites (note tagging, titles, clustering) reach the provider.
    """
    svc = LLMService()
    with patch(
        "litellm.acompletion", new_callable=AsyncMock, return_value=_response("ok")
    ) as mock_ac:
        await svc.complete([{"role": "user", "content": "hi"}], background=True)
    assert mock_ac.call_args.kwargs["model"].startswith("openai/")


@pytest.mark.asyncio
async def test_streaming_falls_back_to_local(cloud_routing):
    svc = LLMService()
    calls: list[dict] = []

    async def chunks():
        for text in ("local ", "stream"):
            delta = MagicMock()
            delta.content = text
            choice = MagicMock()
            choice.delta = delta
            chunk = MagicMock()
            chunk.choices = [choice]
            yield chunk

    async def side_effect(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise litellm.APIConnectionError(
                message="offline", llm_provider="openai", model="gpt-5-mini"
            )
        return chunks()

    with patch("litellm.acompletion", side_effect=side_effect):
        stream = await svc.stream_messages([{"role": "user", "content": "hi"}])
        out = "".join([token async for token in stream])

    assert out == "local stream"
    assert calls[1]["model"].startswith("ollama/")
