"""Tests for POST /explain and POST /glossary/{document_id} endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.explain import (
    MODE_INSTRUCTIONS,
    ExplainService,
)
from app.types import ScoredChunk


def _make_chunk(text: str = "Sample context text.") -> ScoredChunk:
    return ScoredChunk(
        chunk_id="c1",
        document_id="doc-1",
        text=text,
        section_heading="Introduction",
        page=1,
        score=0.9,
        source="both",
    )


@pytest.mark.asyncio
async def test_each_mode_uses_different_instruction():
    """Each explain mode injects a distinct instruction into the system prompt."""
    captured: dict[str, str] = {}

    for mode in ["plain", "eli5", "analogy", "formal"]:
        retriever = MagicMock()
        retriever.retrieve = AsyncMock(return_value=[_make_chunk()])
        system_calls: list[str] = []

        async def make_gen():
            yield "token"

        llm = MagicMock()

        async def capturing_generate(prompt, system="", **kwargs):
            system_calls.append(system)
            async def gen():
                yield "token"
            return gen()

        llm.generate = AsyncMock(side_effect=capturing_generate)

        with (
            patch("app.services.explain.get_retriever", return_value=retriever),
            patch("app.services.explain.get_llm_service", return_value=llm),
        ):
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
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[_make_chunk()])

    async def make_gen():
        yield "Hello"
        yield " world"

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=make_gen())

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
    ):
        svc = ExplainService()
        events = [e async for e in svc.stream_explain("text", "doc-1", "plain")]

    token_events = [e for e in events if '"token"' in e]
    done_events = [e for e in events if '"done"' in e]
    assert len(token_events) == 2
    assert len(done_events) == 1
    assert json.loads(done_events[0].removeprefix("data: ").strip())["done"] is True


@pytest.mark.asyncio
async def test_extract_glossary_returns_list():
    """Glossary extraction returns a list of term dicts."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[_make_chunk("Entanglement is a quantum phenomenon.")]
    )
    glossary_json = json.dumps(
        [{"term": "Entanglement", "definition": "A quantum phenomenon.", "category": "concept"}]
    )
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=glossary_json)

    persisted = [{"id": "t1", "term": "Entanglement", "definition": "A quantum phenomenon.",
                  "category": "concept", "first_mention_section_id": None,
                  "created_at": None, "updated_at": None}]

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
        patch.object(
            ExplainService, "_upsert_terms",
            new_callable=AsyncMock, return_value=persisted,
        ),
    ):
        svc = ExplainService()
        result = await svc.extract_glossary("doc-1")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["term"] == "Entanglement"


@pytest.mark.asyncio
async def test_extract_glossary_strips_markdown_fences():
    """Glossary handles LLM responses wrapped in markdown code fences."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[_make_chunk("Some text.")])
    glossary_json = (
        "```json\n"
        '[{"term": "Qubit", "definition": "Quantum bit.", "category": "technical"}]\n'
        "```"
    )
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=glossary_json)

    persisted = [{"id": "t1", "term": "Qubit", "definition": "Quantum bit.",
                  "category": "technical", "first_mention_section_id": None,
                  "created_at": None, "updated_at": None}]

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
        patch.object(
            ExplainService, "_upsert_terms",
            new_callable=AsyncMock, return_value=persisted,
        ),
    ):
        svc = ExplainService()
        result = await svc.extract_glossary("doc-1")

    assert isinstance(result, list)
    assert result[0]["term"] == "Qubit"


@pytest.mark.asyncio
async def test_extract_glossary_returns_empty_on_no_chunks():
    """Returns empty list when retriever finds no chunks."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    llm = MagicMock()

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
    ):
        svc = ExplainService()
        result = await svc.extract_glossary("doc-1")

    assert result == []
    llm.generate.assert_not_called()


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


def test_glossary_endpoint_returns_list():
    """POST /glossary/{id} returns a JSON list."""
    mock_svc = MagicMock()
    mock_svc.extract_glossary = AsyncMock(
        return_value=[{"term": "Qubit", "definition": "Quantum bit.", "first_mention_page": 1}]
    )

    with patch("app.routers.explain.get_explain_service", return_value=mock_svc):
        with TestClient(app) as client:
            resp = client.post("/explain/glossary/doc-1")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["term"] == "Qubit"
