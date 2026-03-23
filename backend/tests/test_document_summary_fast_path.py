"""Tests for S76: Document summary fast-path using section summaries.

(a) test_fast_path_used_when_section_summaries_exist:
    10 SectionSummaryModel rows → pregenerate() calls LLM exactly once per mode (3 total).

(b) test_slow_path_fallback_when_no_section_summaries:
    No SectionSummaryModel rows + chunks with total tokens > MAP_TOKEN_THRESHOLD
    → pregenerate() calls LLM more than 3 times (map-reduce + mode calls).

(c) test_section_reduce_cached_as_db_row:
    After fast path runs, SummaryModel has a row with mode='_section_reduce'.

(d) test_fast_path_skipped_with_fewer_than_3_units:
    Only 2 SectionSummaryModel rows → slow path is taken, no '_section_reduce' row.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, SectionSummaryModel, SummaryModel
from app.services.summarizer import SummarizationService

# MAP_TOKEN_THRESHOLD from summarizer — keep in sync
_MAP_TOKEN_THRESHOLD = 8000
_MAP_BATCH_TOKENS = 3_000


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
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

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_document(factory, doc_id: str) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                format="txt",
                content_type="book",
                word_count=1000,
                page_count=10,
                file_path="/tmp/test.txt",
                stage="complete",
                tags=[],
            )
        )
        await session.commit()


async def _insert_section_summaries(factory, doc_id: str, count: int) -> None:
    async with factory() as session:
        for i in range(count):
            session.add(
                SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    heading=f"Section {i}",
                    content=f"Summary content for section {i}.",
                    unit_index=i,
                )
            )
        await session.commit()


async def _insert_chunks(factory, doc_id: str, count: int, token_count: int = 3000) -> None:
    """Insert chunks with the given token_count each."""
    async with factory() as session:
        for i in range(count):
            session.add(
                ChunkModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    text=f"Chunk text content {i}. " * 100,
                    token_count=token_count,
                    page_number=i,
                    chunk_index=i,
                )
            )
        await session.commit()


def _make_mock_llm(return_text: str = "Generated summary.") -> AsyncMock:
    """Return a mock LLMService whose generate() always returns return_text."""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=return_text)
    return mock_llm


# ---------------------------------------------------------------------------
# (a) test_fast_path_used_when_section_summaries_exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_used_when_section_summaries_exist(test_db):
    """When >= 3 SectionSummaryModel rows exist, pregenerate makes exactly 3 LLM calls."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summaries(factory, doc_id, count=10)

    mock_llm = _make_mock_llm()

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        await svc.pregenerate(doc_id)

    # Fast path: one LLM call per mode (one_sentence, executive, detailed) = 3 total.
    # No map-reduce calls.
    assert mock_llm.generate.call_count == 3, (
        f"Expected 3 LLM calls (one per mode), got {mock_llm.generate.call_count}"
    )


# ---------------------------------------------------------------------------
# (b) test_slow_path_fallback_when_no_section_summaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_path_fallback_when_no_section_summaries(test_db):
    """When no SectionSummaryModel rows exist, pregenerate runs chunk-based map-reduce."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # 3 chunks × 3000 tokens each = 9000 > MAP_TOKEN_THRESHOLD (8000) → map-reduce triggered.
    # With _MAP_BATCH_TOKENS=3000, each chunk becomes its own batch → 3 map calls.
    # Then 3 mode calls. Total: 6 generate calls.
    await _insert_chunks(factory, doc_id, count=3, token_count=3000)

    mock_llm = _make_mock_llm()

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        await svc.pregenerate(doc_id)

    # Slow path: map calls (>= 1 per batch) + 3 mode calls = > 3 total.
    assert mock_llm.generate.call_count > 3, (
        f"Expected > 3 LLM calls (map-reduce slow path), got {mock_llm.generate.call_count}"
    )


# ---------------------------------------------------------------------------
# (c) test_section_reduce_cached_as_db_row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_reduce_cached_as_db_row(test_db):
    """After fast path pregenerate, a '_section_reduce' row exists in SummaryModel."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summaries(factory, doc_id, count=5)

    mock_llm = _make_mock_llm()

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        await svc.pregenerate(doc_id)

    async with factory() as session:
        result = await session.execute(
            select(SummaryModel)
            .where(SummaryModel.document_id == doc_id)
            .where(SummaryModel.mode == "_section_reduce")
        )
        row = result.scalar_one_or_none()

    assert row is not None, "_section_reduce row should exist in SummaryModel after fast path"
    # Content should be the concatenated section summaries in markdown form
    assert "Section 0" in row.content


# ---------------------------------------------------------------------------
# (d) test_fast_path_skipped_with_fewer_than_3_units
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_skipped_with_fewer_than_3_units(test_db):
    """When < 3 SectionSummaryModel rows exist, slow path is taken (no _section_reduce row)."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # Only 2 section summaries — below the 3-unit threshold
    await _insert_section_summaries(factory, doc_id, count=2)

    # Small chunk so slow path doesn't trigger map-reduce (total tokens < threshold)
    await _insert_chunks(factory, doc_id, count=1, token_count=50)

    mock_llm = _make_mock_llm()

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        await svc.pregenerate(doc_id)

    # No _section_reduce row — fast path was not taken
    async with factory() as session:
        result = await session.execute(
            select(SummaryModel)
            .where(SummaryModel.document_id == doc_id)
            .where(SummaryModel.mode == "_section_reduce")
        )
        row = result.scalar_one_or_none()

    assert row is None, "_section_reduce should NOT exist when < 3 section summary units"

    # Verify summaries were still generated via slow path
    assert mock_llm.generate.call_count >= 3, (
        f"Expected >= 3 LLM calls for 3 modes via slow path, got {mock_llm.generate.call_count}"
    )
