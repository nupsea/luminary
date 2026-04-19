"""Tests for SectionSummarizerService (S75).

(a) test_grouping_caps_at_100_units — 300 qualifying sections → <= 100 DB rows
(b) test_short_sections_skipped — sections with preview < 200 chars are excluded
(c) test_ollama_offline_returns_zero — ServiceUnavailableError → returns 0, no raise
(d) test_get_sections_endpoint_returns_list — GET /summarize/{id}/sections returns ordered list
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, SectionModel, SectionSummaryModel
from app.services.section_summarizer import SectionSummarizerService

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
        doc = DocumentModel(
            id=doc_id,
            title="Test Doc",
            format="txt",
            content_type="book",
            word_count=1000,
            page_count=1,
            file_path="/tmp/test.txt",
            stage="complete",
            tags=[],
        )
        session.add(doc)
        await session.commit()


async def _insert_sections(
    factory, doc_id: str, count: int, preview_len: int = 300
) -> list[SectionModel]:
    """Insert `count` sections with preview of given length."""
    sections = []
    async with factory() as session:
        for i in range(count):
            s = SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading=f"Section {i}",
                level=1,
                page_start=i,
                page_end=i,
                section_order=i,
                preview="A" * preview_len,
            )
            session.add(s)
            sections.append(s)
        await session.commit()
    return sections


# ---------------------------------------------------------------------------
# (a) test_grouping_caps_at_100_units
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grouping_caps_at_100_units(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_sections(factory, doc_id, count=300, preview_len=300)

    # Mock LiteLLM to return instantly without making real calls
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Summary text."

    with patch("litellm.acompletion", return_value=mock_response):
        svc = SectionSummarizerService()
        inserted = await svc.generate(doc_id, concurrency=10)

    async with factory() as session:
        rows = await session.execute(
            select(SectionSummaryModel).where(SectionSummaryModel.document_id == doc_id)
        )
        db_count = len(list(rows.scalars().all()))

    assert db_count <= 100, f"Expected <= 100 units, got {db_count}"
    assert inserted == db_count


# ---------------------------------------------------------------------------
# (b) test_short_sections_skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_sections_skipped(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # 5 qualifying + 5 too-short
    await _insert_sections(factory, doc_id, count=5, preview_len=300)  # qualify
    await _insert_sections(factory, doc_id, count=5, preview_len=50)  # too short

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Summary."

    with patch("litellm.acompletion", return_value=mock_response):
        svc = SectionSummarizerService()
        inserted = await svc.generate(doc_id, concurrency=5)

    assert inserted == 5, f"Expected 5 summaries (short skipped), got {inserted}"


# ---------------------------------------------------------------------------
# (c) test_ollama_offline_returns_zero
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_offline_returns_zero(test_db):
    import litellm

    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_sections(factory, doc_id, count=3, preview_len=300)

    with patch(
        "litellm.acompletion",
        side_effect=litellm.ServiceUnavailableError(
            message="Ollama offline", llm_provider="ollama", model="ollama/mistral"
        ),
    ):
        svc = SectionSummarizerService()
        result = await svc.generate(doc_id)

    assert result == 0, f"Expected 0 when Ollama offline, got {result}"


# ---------------------------------------------------------------------------
# (d) test_get_sections_endpoint_returns_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sections_endpoint_returns_list(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # Pre-insert section summaries directly (bypassing LLM)
    async with factory() as session:
        for i in range(3):
            session.add(
                SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    heading=f"Heading {i}",
                    content=f"Summary {i}",
                    unit_index=i,
                )
            )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/summarize/{doc_id}/sections")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3
    # Verify ordering by unit_index
    assert [d["unit_index"] for d in data] == [0, 1, 2]
    assert data[0]["heading"] == "Heading 0"
    assert data[2]["content"] == "Summary 2"


# ---------------------------------------------------------------------------
# (e) test_get_sections_endpoint_empty_for_unknown_doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sections_endpoint_empty_for_unknown_doc(test_db):
    """GET /summarize/{id}/sections returns [] for pre-V2 documents (not 404)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/summarize/{uuid.uuid4()}/sections")

    assert resp.status_code == 200
    assert resp.json() == []
