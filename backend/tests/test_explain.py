"""Tests for POST /explain endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.explain import (
    MODE_INSTRUCTIONS,
    ExplainService,
)


def _capturing_llm(calls: list[tuple[str, str]]) -> MagicMock:
    async def capturing_generate(prompt, system="", **kwargs):
        calls.append((prompt, system))

        async def gen():
            yield "token"

        return gen()

    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=capturing_generate)
    return llm


def _retriever_returning(*texts: str) -> MagicMock:
    retriever = MagicMock()
    retriever.keyword_search = AsyncMock(return_value=[MagicMock(text=t) for t in texts])
    return retriever


@pytest.mark.asyncio
async def test_each_mode_uses_different_instruction():
    """Each explain mode injects a distinct instruction into the system prompt."""
    captured: dict[str, str] = {}

    for mode in MODE_INSTRUCTIONS:
        calls: list[tuple[str, str]] = []
        with (
            patch("app.services.explain.get_llm_service", return_value=_capturing_llm(calls)),
            patch("app.services.explain.get_retriever", return_value=_retriever_returning()),
        ):
            async for _ in ExplainService().stream_explain("quantum", "doc-1", mode):
                pass
        captured[mode] = calls[0][1]

    for mode, expected in MODE_INSTRUCTIONS.items():
        assert expected in captured[mode], f"Mode {mode!r} missing its instruction"

    assert len(set(captured.values())) == len(MODE_INSTRUCTIONS)


@pytest.mark.asyncio
async def test_define_grounds_a_bare_term_in_document_passages():
    """A one-word selection is sent with passages from its own document, not alone."""
    calls: list[tuple[str, str]] = []
    retriever = _retriever_returning("A lakehouse combines a data lake with warehouse tables.")

    with (
        patch("app.services.explain.get_llm_service", return_value=_capturing_llm(calls)),
        patch("app.services.explain.get_retriever", return_value=retriever),
    ):
        async for _ in ExplainService().stream_explain("lakehouse", "doc-7", "define"):
            pass

    retriever.keyword_search.assert_awaited_once_with("lakehouse", ["doc-7"], k=4)
    prompt = calls[0][0]
    assert "A lakehouse combines a data lake with warehouse tables." in prompt
    assert "Define the selected term." in prompt


@pytest.mark.asyncio
async def test_failed_context_lookup_still_explains():
    """A retrieval error degrades to the selection alone rather than failing the stream."""
    calls: list[tuple[str, str]] = []
    retriever = MagicMock()
    retriever.keyword_search = AsyncMock(side_effect=RuntimeError("fts down"))

    with (
        patch("app.services.explain.get_llm_service", return_value=_capturing_llm(calls)),
        patch("app.services.explain.get_retriever", return_value=retriever),
    ):
        events = [e async for e in ExplainService().stream_explain("lakehouse", "d", "define")]

    assert "Document excerpts" not in calls[0][0]
    assert any('"done"' in e for e in events)


@pytest.mark.asyncio
async def test_stream_explain_yields_token_events_then_done():
    """Stream yields data: {token} events followed by data: {done: true}."""

    async def make_gen():
        yield "Hello"
        yield " world"

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=make_gen())

    with (
        patch("app.services.explain.get_llm_service", return_value=llm),
        patch("app.services.explain.get_retriever", return_value=_retriever_returning()),
    ):
        events = [e async for e in ExplainService().stream_explain("text", "doc-1", "plain")]

    token_events = [e for e in events if '"token"' in e]
    done_events = [e for e in events if '"done"' in e]
    assert len(token_events) == 2
    assert len(done_events) == 1
    assert json.loads(done_events[0].removeprefix("data: ").strip())["done"] is True


@pytest.mark.parametrize("mode", ["define", "plain"])
def test_explain_endpoint_streams_sse(mode):
    """POST /explain returns text/event-stream with token and done events."""

    async def fake_stream(text, doc_id, mode):
        yield 'data: {"token": "Hello"}\n\n'
        yield 'data: {"done": true}\n\n'

    mock_svc = MagicMock()
    mock_svc.stream_explain = fake_stream

    with patch("app.routers.explain.get_explain_service", return_value=mock_svc):
        with TestClient(app) as client:
            resp = client.post(
                "/explain",
                json={"text": "quantum", "document_id": "doc-1", "mode": mode},
            )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert '"token"' in resp.text
    assert '"done"' in resp.text
