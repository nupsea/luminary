"""V2 pipeline integration tests (S80).

Tests the full v2 stack (section summaries, fast-path document summary,
intent routing, library overview) against the three corpus books.

DB-dependent integration tests are marked @pytest.mark.slow — run via:
    cd backend && uv run pytest tests/test_v2_pipeline.py -v -m slow

or via the Makefile target:
    make test-v2

Pure unit tests (test_keyword_summary_word, test_streaming_not_buffered) carry no
slow marker and run in the default CI path.

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

# pytestmark is NOT set at module level so that the pure unit tests
# (test_keyword_summary_word, test_streaming_not_buffered) run in the
# default fast CI path.  DB-dependent integration tests carry the marker
# individually via @pytest.mark.slow.


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


def _make_mock_llm(
    answer: str = "Test answer.",
    section_heading: str = "Chapter 1",
) -> MagicMock:
    """Build a mock LLM service that yields a canned answer with citations.

    Uses side_effect to create a fresh async generator per call, avoiding
    exhausted-generator issues when generate() is called more than once.
    """
    citations_json = (
        f'\n{{"citations":[{{"section_heading":"{section_heading}",'
        f'"page":1,"excerpt":"relevant text"}}],"confidence":"high"}}'
    )
    full_response = answer + citations_json

    async def _side_effect(*_args, **_kwargs):
        return _fake_stream([full_response])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_side_effect)
    return mock_llm


# ---------------------------------------------------------------------------
# (a) test_section_summaries_generated_for_all_books
# ---------------------------------------------------------------------------


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
@pytest.mark.asyncio
async def test_intent_routing_summary(all_books_ingested):
    """POST /qa summary question with cached exec summary returns HTTP 200.

    S78 AC: summary_node returns the cached executive summary directly as the answer
    (confidence='high'); no LLM call needed. The conftest ingestion mocked LiteLLM
    to return 'book' for all LLM calls, so every book has an executive summary row
    with content='book'. The done event must have non-empty answer and confidence='high'.
    """
    ids = _book_ids(all_books_ingested)
    alice_id = ids.get("Alice in Wonderland")
    assert alice_id, "Alice in Wonderland not in all_books_ingested"

    # No LLM mock needed — summary_node serves the cached executive summary directly
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/qa",
            json={
                "question": "summarize this document",
                "document_ids": [alice_id],
                "scope": "single",
            },
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    done = _parse_sse_done(resp.text)
    assert done.get("done"), f"No done event in SSE response: {resp.text[:500]}"
    assert done.get("answer"), f"Expected non-empty answer, got: {done}"
    assert done.get("confidence") == "high", (
        f"Expected confidence='high' from cached summary, got: {done.get('confidence')}"
    )


# ---------------------------------------------------------------------------
# (d) test_intent_routing_factual
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_intent_routing_factual(all_books_ingested):
    """POST /qa factual question returns HTTP 200 with non-empty citations.

    S80 AC: mock LLM returns a response with citation JSON block containing
    a non-empty section_heading. Done event must have citations list non-empty
    and first citation must have a non-empty section_heading.
    """
    ids = _book_ids(all_books_ingested)
    alice_id = ids.get("Alice in Wonderland")
    assert alice_id, "Alice in Wonderland not in all_books_ingested"

    mock_llm = _make_mock_llm(
        "The White Rabbit is a character who leads Alice into Wonderland.",
        section_heading="Chapter I: Down the Rabbit-Hole",
    )

    # LLM call now happens in stream_answer() (app.services.qa), not chat_graph
    with patch("app.services.qa.get_llm_service", return_value=mock_llm):
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
    citations = done.get("citations") or []
    assert citations, f"Expected non-empty citations list, got: {done}"
    assert citations[0].get("section_heading"), (
        f"Expected non-empty section_heading in first citation, got: {citations[0]}"
    )


# ---------------------------------------------------------------------------
# (e) test_intent_routing_comparative
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_intent_routing_comparative(all_books_ingested):
    """POST /qa comparative question returns HTTP 200."""
    mock_llm = _make_mock_llm(
        "Alice is a curious girl. The Time Traveller is an inventor."
    )

    with patch("app.services.qa.get_llm_service", return_value=mock_llm):
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


@pytest.mark.slow
@pytest.mark.asyncio
async def test_intent_routing_relational(all_books_ingested):
    """POST /qa relational question returns HTTP 200."""
    ids = _book_ids(all_books_ingested)
    odyssey_id = ids.get("The Odyssey")
    assert odyssey_id, "The Odyssey not in all_books_ingested"

    mock_llm = _make_mock_llm(
        "Odysseus and Telemachus are father and son. Telemachus seeks his missing father."
    )

    with patch("app.services.qa.get_llm_service", return_value=mock_llm):
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


@pytest.mark.slow
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


# ---------------------------------------------------------------------------
# (h) test_keyword_summary_word — unit test, no DB required
# ---------------------------------------------------------------------------


def test_keyword_summary_word():
    """classify_intent_heuristic('summary') returns intent='summary'."""
    from app.services.intent import classify_intent_heuristic  # noqa: PLC0415

    intent, conf = classify_intent_heuristic("Please give me a summary of this")
    assert intent == "summary", f"Expected 'summary', got '{intent}'"
    assert conf > 0.0, f"Expected positive confidence, got {conf}"


# ---------------------------------------------------------------------------
# (i) test_streaming_not_buffered — unit test, no DB required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_not_buffered():
    """First SSE 'token' event arrives before all LLM tokens are generated.

    Verifies true streaming: stream_answer() must yield tokens progressively,
    not buffer the full LLM response before sending the first SSE event.
    """
    from app.services.qa import get_qa_service  # noqa: PLC0415

    token_order: list[str] = []
    generation_complete = False

    async def _slow_stream(*_args, **_kwargs):
        nonlocal generation_complete
        tokens = ["Hello", " World", " answer.", '{"citations":[],"confidence":"high"}']
        for tok in tokens:
            token_order.append(tok)
            yield tok
        generation_complete = True

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_slow_stream)

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "answer": "",
            "confidence": "medium",
            "citations": [],
            "chunks": [],
            "section_context": "",
            "intent": "factual",
            "_llm_prompt": "What is the answer?",
            "_system_prompt": "You are a helpful assistant.",
        }
    )

    collected_tokens: list[str] = []
    first_token_at_generation_step: int | None = None

    qa = get_qa_service()
    with (
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
    ):
        async for chunk in qa.stream_answer(
            question="What is the answer?",
            document_ids=[],
            scope="all",
            model=None,
        ):
            if chunk.startswith("data: "):
                try:
                    obj = json.loads(chunk[6:])
                    tok = obj.get("token")
                    if tok:
                        collected_tokens.append(tok)
                        if first_token_at_generation_step is None:
                            first_token_at_generation_step = len(token_order)
                except Exception:
                    pass

    assert collected_tokens, "No SSE token events were emitted"
    # First token emitted before all LLM tokens were generated
    assert first_token_at_generation_step is not None
    assert first_token_at_generation_step < len(token_order), (
        f"First SSE token emitted only after all {len(token_order)} LLM tokens "
        f"were generated — streaming is buffered, not progressive."
    )
