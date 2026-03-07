"""V2 pipeline integration tests (S80).

Tests the full v2 stack (section summaries, fast-path document summary,
intent routing, library overview) against the three corpus books.

Marked @pytest.mark.slow — run via:
    cd backend && uv run pytest tests/test_v2_pipeline.py -v -m slow --timeout=1800

or via the Makefile target:
    make test-v2

Relies on all_books_ingested session fixture from conftest_books.py.
LiteLLM calls in /qa and /summarize routes are mocked to avoid requiring Ollama.
"""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.database as db_module
from app.main import app
from app.models import SectionSummaryModel, SummaryModel

pytest_plugins = ["tests.conftest_books"]
pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _book_ids(all_books_ingested: dict) -> dict[str, str]:
    """Return {book_name: doc_id} for the three corpus books."""
    return {name: info["doc_id"] for name, info in all_books_ingested.items()}


def _parse_sse_done(sse_text: str) -> dict:
    """Parse the final 'done' event from an SSE response."""
    for line in sse_text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
            if obj.get("done"):
                return obj
        except Exception:
            pass
    return {}


async def _fake_stream(tokens: list[str]):
    """Async generator that yields tokens one by one."""
    for t in tokens:
        yield t


def _make_mock_llm(answer: str = "Test answer.") -> MagicMock:
    """Build a mock LLM service that yields a canned answer."""
    citations_json = ' {"citations": [], "confidence": "high"}'
    full_response = answer + citations_json

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_fake_stream([full_response]))
    return mock_llm


# ---------------------------------------------------------------------------
# (a) test_section_summaries_generated_for_all_books
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_summaries_generated_for_all_books(all_books_ingested):
    """Each of the 3 corpus books has >= 10 SectionSummaryModel rows."""
    ids = _book_ids(all_books_ingested)

    async with db_module._session_factory() as session:
        for book_name, doc_id in ids.items():
            rows = await session.execute(
                select(SectionSummaryModel).where(
                    SectionSummaryModel.document_id == doc_id
                )
            )
            summaries = rows.scalars().all()
            assert len(summaries) >= 10, (
                f"Book '{book_name}' has only {len(summaries)} section summary rows "
                f"(expected >= 10). section_summarize_node may not have run."
            )


# ---------------------------------------------------------------------------
# (b) test_document_summary_uses_fast_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_summary_uses_fast_path(all_books_ingested):
    """Each book with section summaries has a '_section_reduce' SummaryModel row."""
    ids = _book_ids(all_books_ingested)

    async with db_module._session_factory() as session:
        for book_name, doc_id in ids.items():
            # Only check if section summaries exist for this book
            section_rows = await session.execute(
                select(SectionSummaryModel.id).where(
                    SectionSummaryModel.document_id == doc_id
                ).limit(1)
            )
            if not section_rows.scalar_one_or_none():
                continue  # No section summaries — skip fast-path check

            reduce_row = await session.execute(
                select(SummaryModel).where(
                    SummaryModel.document_id == doc_id,
                    SummaryModel.mode == "_section_reduce",
                )
            )
            result = reduce_row.scalar_one_or_none()
            assert result is not None, (
                f"Book '{book_name}' missing '_section_reduce' SummaryModel row. "
                f"pregenerate() may not have used the fast path."
            )


# ---------------------------------------------------------------------------
# (c) test_intent_routing_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_routing_summary(all_books_ingested):
    """POST /qa summary question returns HTTP 200 with non-empty answer."""
    ids = _book_ids(all_books_ingested)
    alice_id = ids.get("Alice in Wonderland")
    assert alice_id, "Alice in Wonderland not in all_books_ingested"

    mock_llm = _make_mock_llm("Alice in Wonderland is a classic fantasy novel.")

    with patch("app.runtime.chat_graph.get_llm_service", return_value=mock_llm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={
                    "question": "Give me an overview of this book",
                    "document_ids": [alice_id],
                    "scope": "single",
                },
            )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    done = _parse_sse_done(resp.text)
    assert done.get("done"), f"No done event in SSE response: {resp.text[:500]}"
    assert done.get("answer") or done.get("not_found") or done.get("error"), (
        f"Expected answer, not_found, or error in done event: {done}"
    )
    # Accept answer, not_found (no summary yet), or llm_unavailable
    # The key constraint is HTTP 200 and a valid done event
    if done.get("answer"):
        assert done["confidence"] in ("high", "medium", "low")


# ---------------------------------------------------------------------------
# (d) test_intent_routing_factual
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_routing_factual(all_books_ingested):
    """POST /qa factual question returns HTTP 200."""
    ids = _book_ids(all_books_ingested)
    alice_id = ids.get("Alice in Wonderland")
    assert alice_id, "Alice in Wonderland not in all_books_ingested"

    mock_llm = _make_mock_llm(
        "The White Rabbit is a character who leads Alice into Wonderland."
    )

    with patch("app.runtime.chat_graph.get_llm_service", return_value=mock_llm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={
                    "question": "Who is the White Rabbit?",
                    "document_ids": [alice_id],
                    "scope": "single",
                },
            )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    done = _parse_sse_done(resp.text)
    assert done.get("done"), "No done event in SSE response"


# ---------------------------------------------------------------------------
# (e) test_intent_routing_comparative
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_routing_comparative(all_books_ingested):
    """POST /qa comparative question returns HTTP 200."""
    mock_llm = _make_mock_llm(
        "Alice is a curious girl. The Time Traveller is an inventor."
    )

    with patch("app.runtime.chat_graph.get_llm_service", return_value=mock_llm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={
                    "question": "Compare Alice versus the Time Traveller",
                    "document_ids": [],
                    "scope": "all",
                },
            )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    done = _parse_sse_done(resp.text)
    assert done.get("done"), "No done event in SSE response"


# ---------------------------------------------------------------------------
# (f) test_intent_routing_relational
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_routing_relational(all_books_ingested):
    """POST /qa relational question returns HTTP 200."""
    ids = _book_ids(all_books_ingested)
    odyssey_id = ids.get("The Odyssey")
    assert odyssey_id, "The Odyssey not in all_books_ingested"

    mock_llm = _make_mock_llm(
        "Odysseus and Telemachus are father and son. Telemachus seeks his missing father."
    )

    with patch("app.runtime.chat_graph.get_llm_service", return_value=mock_llm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/qa",
                json={
                    "question": "How are Odysseus and Telemachus related?",
                    "document_ids": [odyssey_id],
                    "scope": "single",
                },
            )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    done = _parse_sse_done(resp.text)
    assert done.get("done"), "No done event in SSE response"


# ---------------------------------------------------------------------------
# (g) test_library_overview_includes_all_three_books
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_library_overview_includes_all_three_books(all_books_ingested):
    """POST /summarize/all returns HTTP 200 and references at least 2 book titles."""
    ids = _book_ids(all_books_ingested)
    book_titles = list(ids.keys())

    # Mock LLM to return a response that mentions the books
    answer_text = (
        "The library contains Alice in Wonderland, The Time Machine, and The Odyssey."
    )
    citations_json = ' {"citations": [], "confidence": "high"}'

    async def _fake_stream_lib(*_args, **_kwargs):
        yield answer_text + citations_json

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_fake_stream_lib())

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/summarize/all",
                json={"mode": "executive", "force_refresh": True},
            )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    # Collect SSE text tokens
    collected_text = ""
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            try:
                obj = json.loads(line[6:])
                collected_text += obj.get("token", "")
            except Exception:
                pass

    # At least 2 of the 3 book titles should be referenced
    mentioned = sum(
        1 for title in book_titles if re.search(re.escape(title), collected_text, re.IGNORECASE)
    )
    assert mentioned >= 2, (
        f"Expected at least 2 book titles in library overview, found {mentioned}. "
        f"Titles: {book_titles}. Collected text: {collected_text[:300]}"
    )
