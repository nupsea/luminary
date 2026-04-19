"""Tests for book ingestion — section-boundary chunking and section_id linking (S66).

(a) test_book_chunks_have_section_id
(b) test_book_chunks_do_not_cross_section_boundary
(c) test_sections_endpoint_returns_chunk_count
(d) test_book_without_headings_gets_single_section
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, SectionModel
from app.workflows.ingestion import IngestionState, _chunk_book

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

CHAPTER_1 = "Chapter One content. " * 30  # ~150 words — enough for at least 1 chunk
CHAPTER_2 = "Chapter Two content. " * 30
CHAPTER_3 = "Chapter Three content. " * 30

THREE_CHAPTER_SECTIONS = [
    {"heading": "Chapter 1", "level": 1, "text": CHAPTER_1, "page_start": 0, "page_end": 0},
    {"heading": "Chapter 2", "level": 1, "text": CHAPTER_2, "page_start": 1, "page_end": 1},
    {"heading": "Chapter 3", "level": 1, "text": CHAPTER_3, "page_start": 2, "page_end": 2},
]


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


def _make_doc(doc_id: str, **kwargs) -> DocumentModel:
    defaults = {
        "id": doc_id,
        "title": "Test Book",
        "format": "txt",
        "content_type": "book",
        "word_count": 500,
        "page_count": 0,
        "file_path": "/tmp/test.txt",
        "stage": "chunking",
        "tags": [],
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


def _make_state(doc_id: str, sections: list[dict]) -> IngestionState:
    return IngestionState(
        document_id=doc_id,
        file_path="/tmp/test.txt",
        format="txt",
        parsed_document={
            "title": "Test Book",
            "format": "txt",
            "pages": 0,
            "word_count": sum(len(s["text"].split()) for s in sections),
            "sections": sections,
            "raw_text": " ".join(s["text"] for s in sections),
        },
        content_type="book",
        chunks=None,
        status="chunking",
        error=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_book_chunks_have_section_id(test_db):
    """All chunks for a book doc have non-None section_id after ingestion via _chunk_book."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    state = _make_state(doc_id, THREE_CHAPTER_SECTIONS)
    result = await _chunk_book(state, state["parsed_document"], doc_id)

    assert result["status"] == "embedding"
    assert len(result["chunks"]) > 0

    async with factory() as session:
        chunks_result = await session.execute(
            select(ChunkModel).where(ChunkModel.document_id == doc_id)
        )
        chunks = chunks_result.scalars().all()

    assert len(chunks) > 0, "Expected at least one chunk"
    for chunk in chunks:
        assert chunk.section_id is not None, (
            f"Chunk {chunk.id} has section_id=None — book chunks must be linked to a section"
        )


@pytest.mark.anyio
async def test_book_chunks_do_not_cross_section_boundary(test_db):
    """No chunk's text contains content from two different sections."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    # Use distinct marker words per chapter to detect cross-boundary chunks
    sections = [
        {
            "heading": "Chapter 1",
            "level": 1,
            "text": "CHAPTERONE " * 80,
            "page_start": 0,
            "page_end": 0,
        },
        {
            "heading": "Chapter 2",
            "level": 1,
            "text": "CHAPTERTWO " * 80,
            "page_start": 1,
            "page_end": 1,
        },
        {
            "heading": "Chapter 3",
            "level": 1,
            "text": "CHAPTERTHREE " * 80,
            "page_start": 2,
            "page_end": 2,
        },
    ]
    state = _make_state(doc_id, sections)
    await _chunk_book(state, state["parsed_document"], doc_id)

    async with factory() as session:
        chunks_result = await session.execute(
            select(ChunkModel).where(ChunkModel.document_id == doc_id)
        )
        chunks = chunks_result.scalars().all()

    markers = ["CHAPTERONE", "CHAPTERTWO", "CHAPTERTHREE"]
    for chunk in chunks:
        present = [m for m in markers if m in chunk.text]
        assert len(present) <= 1, f"Chunk {chunk.id} spans section boundary: contains {present}"


@pytest.mark.anyio
async def test_sections_endpoint_returns_chunk_count(test_db):
    """GET /sections/{document_id} returns each section with chunk_count > 0."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    state = _make_state(doc_id, THREE_CHAPTER_SECTIONS)
    await _chunk_book(state, state["parsed_document"], doc_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/sections/{doc_id}")

    assert resp.status_code == 200
    sections = resp.json()
    assert len(sections) == 3, f"Expected 3 sections, got {len(sections)}"
    for sec in sections:
        assert sec["chunk_count"] > 0, f"Section '{sec['heading']}' has chunk_count=0"
        assert "has_summary" in sec
        assert "section_order" in sec


@pytest.mark.anyio
async def test_book_without_headings_gets_single_section(test_db):
    """Flat book (no sections in parsed_document) gets a single 'Full Text' section."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    flat_text = "A very long flat book text with no chapters. " * 50
    state = IngestionState(
        document_id=doc_id,
        file_path="/tmp/flat.txt",
        format="txt",
        parsed_document={
            "title": "Flat Book",
            "format": "txt",
            "pages": 0,
            "word_count": len(flat_text.split()),
            "sections": [],  # No sections detected by parser
            "raw_text": flat_text,
        },
        content_type="book",
        chunks=None,
        status="chunking",
        error=None,
    )
    result = await _chunk_book(state, state["parsed_document"], doc_id)

    assert result["status"] == "embedding"

    async with factory() as session:
        sections_result = await session.execute(
            select(SectionModel).where(SectionModel.document_id == doc_id)
        )
        sections = sections_result.scalars().all()

        chunks_result = await session.execute(
            select(ChunkModel).where(ChunkModel.document_id == doc_id)
        )
        chunks = chunks_result.scalars().all()

    assert len(sections) == 1, f"Expected 1 section, got {len(sections)}"
    assert sections[0].heading == "Full Text"
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.section_id == sections[0].id, (
            "All chunks in a flat book must link to the single 'Full Text' section"
        )

    # chapter_count on DocumentModel should be 1
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None
    assert doc.chapter_count == 1
