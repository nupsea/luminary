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


@pytest.mark.asyncio
async def test_each_mode_uses_different_instruction():
    """Each explain mode injects a distinct instruction into the system prompt."""
    captured: dict[str, str] = {}

    for mode in ["plain", "eli5", "analogy", "formal"]:
        system_calls: list[str] = []
        llm = MagicMock()

        async def capturing_generate(prompt, system="", **kwargs):
            system_calls.append(system)

            async def gen():
                yield "token"

            return gen()

        llm.generate = AsyncMock(side_effect=capturing_generate)

        with patch("app.services.explain.get_llm_service", return_value=llm):
            svc = ExplainService()
            async for _ in svc.stream_explain("quantum", "doc-1", mode):
                pass

        captured[mode] = system_calls[0] if system_calls else ""

    for mode, expected in MODE_INSTRUCTIONS.items():
        assert expected in captured[mode], f"Mode {mode!r} missing its instruction"

    assert len(set(captured.values())) == 4


@pytest.mark.asyncio
async def test_stream_explain_yields_token_events_then_done():
    """Stream yields data: {token} events followed by data: {done: true}."""

    async def make_gen():
        yield "Hello"
        yield " world"

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=make_gen())

    with patch("app.services.explain.get_llm_service", return_value=llm):
        svc = ExplainService()
        events = [e async for e in svc.stream_explain("text", "doc-1", "plain")]

    token_events = [e for e in events if '"token"' in e]
    done_events = [e for e in events if '"done"' in e]
    assert len(token_events) == 2
    assert len(done_events) == 1
    assert json.loads(done_events[0].removeprefix("data: ").strip())["done"] is True


def test_explain_endpoint_streams_sse():
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
                json={"text": "quantum", "document_id": "doc-1", "mode": "plain"},
            )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert '"token"' in resp.text
    assert '"done"' in resp.text
