"""Tests for S76: Document summary fast-path using section summaries.

(a) test_fast_path_used_when_section_summaries_exist:
    10 SectionSummaryModel rows → pregenerate() calls the LLM once per *generated*
    mode (2 total). `detailed` is assembled from the section summaries themselves,
    which is the shape that mode asks the model to produce, so it costs no call.

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
import app.services.summarizer as summarizer
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, SectionSummaryModel, SummaryModel
from app.services.summarizer import SummarizationService, _input_token_budget

_MAP_TOKEN_THRESHOLD = _input_token_budget()
_MAP_BATCH_TOKENS = 3_000


# Shared fixture


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


# (a) test_fast_path_used_when_section_summaries_exist


@pytest.mark.asyncio
async def test_fast_path_used_when_section_summaries_exist(test_db):
    """When >= 3 SectionSummaryModel rows exist, only the synthesising modes call the LLM."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summaries(factory, doc_id, count=10)

    mock_llm = _make_mock_llm()

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        await svc.pregenerate(doc_id)

    # Fast path: one LLM call each for one_sentence and executive. `detailed` is
    # assembled from the stored section summaries, so it costs no call at all.
    # No map-reduce calls.
    assert mock_llm.generate.call_count == 2, (
        f"Expected 2 LLM calls (one_sentence, executive), got {mock_llm.generate.call_count}"
    )


# (b) test_slow_path_fallback_when_no_section_summaries


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


# (c) test_section_reduce_cached_as_db_row


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


# (d) test_fast_path_skipped_with_fewer_than_3_units


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


# (e) test_detailed_is_assembled_from_section_summaries


@pytest.mark.asyncio
async def test_detailed_is_assembled_from_section_summaries(test_db):
    """`detailed` reproduces every section, without an LLM call and without loss.

    An Ask that arrives while a background call is generating waits for that call
    to finish -- Ollama cannot preempt, and the admission gate cannot touch a call
    it has already admitted. Generating `detailed` ran 107s and 179s on a
    24-section document and was the slowest Ask in both arms of the 2026-08-17
    latency pair, to paraphrase text the section summarizer had already written.
    Assembling removes the call; this asserts it removes no content with it.
    """
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summaries(factory, doc_id, count=10)

    mock_llm = _make_mock_llm()

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        await svc.pregenerate(doc_id)

    async with factory() as session:
        stored = (
            await session.execute(
                select(SummaryModel)
                .where(SummaryModel.document_id == doc_id)
                .where(SummaryModel.mode == "detailed")
            )
        ).scalar_one()
        units = list(
            (
                await session.execute(
                    select(SectionSummaryModel)
                    .where(SectionSummaryModel.document_id == doc_id)
                    .order_by(SectionSummaryModel.unit_index)
                )
            )
            .scalars()
            .all()
        )

    assert stored.content != "Generated summary.", "detailed must not come from the LLM"
    for unit in units:
        assert unit.heading in stored.content, f"section {unit.heading!r} missing from detailed"
        assert unit.content in stored.content, f"body of {unit.heading!r} lost in detailed"


# (f) test_detailed_without_section_summaries_covers_every_batch


@pytest.mark.asyncio
async def test_detailed_without_section_summaries_covers_every_batch(test_db):
    """With no section summaries, `detailed` is generated one batch at a time.

    Splitting bounds how long a single background call runs. It must never bound
    how much of the document is covered, so every batch is summarised and the
    parts are joined in document order.
    """
    svc = SummarizationService()
    text = "\n\n".join(f"## Section {i}\n{'word ' * 900}" for i in range(6))
    batches = summarizer._split_for_detail(text)

    assert len(batches) > 1, "a document this long must split into more than one call"
    assert "".join(batches).replace("\n", "") == text.replace("\n", ""), (
        "splitting must lose no text"
    )

    mock_llm = _make_mock_llm()
    mock_llm.generate = AsyncMock(side_effect=[f"summary {i}" for i in range(len(batches))])
    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        joined = await svc._generate_detailed(text, None)

    assert mock_llm.generate.call_count == len(batches), "every batch gets exactly one call"
    for i in range(len(batches)):
        assert f"summary {i}" in joined, f"batch {i} dropped from the joined summary"
    for call in mock_llm.generate.call_args_list:
        assert call.kwargs["max_tokens"] == summarizer._DETAILED_BATCH_MAX_TOKENS
        assert call.kwargs["background"] is True
