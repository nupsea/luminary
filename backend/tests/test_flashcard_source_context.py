"""Tests for S155: GET /flashcards/{card_id}/source-context endpoint."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel

# ---------------------------------------------------------------------------
# Isolated test DB fixture
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


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_doc(doc_id: str | None = None, title: str = "Test Doc") -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title=title,
        format="txt",
        content_type="notes",
        word_count=100,
        page_count=1,
        file_path="/tmp/test.txt",
        stage="complete",
    )


def _make_section(
    section_id: str,
    doc_id: str,
    heading: str = "Test Section",
    preview: str = "Preview text",
) -> SectionModel:
    return SectionModel(
        id=section_id,
        document_id=doc_id,
        heading=heading,
        level=1,
        page_start=1,
        page_end=2,
        section_order=0,
        preview=preview,
    )


def _make_chunk(
    chunk_id: str | None = None,
    doc_id: str = "doc-1",
    section_id: str | None = None,
    pdf_page_number: int | None = None,
) -> ChunkModel:
    return ChunkModel(
        id=chunk_id or str(uuid.uuid4()),
        document_id=doc_id,
        section_id=section_id,
        text="Chunk text content.",
        token_count=10,
        page_number=1,
        chunk_index=0,
        pdf_page_number=pdf_page_number,
    )


def _make_flashcard(
    card_id: str | None = None,
    doc_id: str | None = None,
    chunk_id: str | None = None,
) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=card_id or str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        source="document",
        deck="default",
        question="What is X?",
        answer="X is Y.",
        source_excerpt="x is y",
        difficulty="medium",
        is_user_edited=False,
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_context_returns_correct_fields(test_db):
    """GET /flashcards/{id}/source-context returns section_heading, document_title, etc."""
    _, factory, _ = test_db
    doc_id = "doc-sc-1"
    sec_id = "sec-sc-1"
    chunk_id = "chunk-sc-1"
    card_id = "card-sc-1"

    async with factory() as session:
        session.add(_make_doc(doc_id, title="Domain-Driven Design"))
        session.add(_make_section(sec_id, doc_id, heading="Aggregates", preview="An aggregate is a cluster"))
        session.add(_make_chunk(chunk_id, doc_id, section_id=sec_id, pdf_page_number=42))
        session.add(_make_flashcard(card_id, doc_id, chunk_id=chunk_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{card_id}/source-context")

    assert resp.status_code == 200
    data = resp.json()
    assert data["section_heading"] == "Aggregates"
    assert data["document_title"] == "Domain-Driven Design"
    assert data["section_preview"] == "An aggregate is a cluster"
    assert data["pdf_page_number"] == 42
    assert data["section_id"] == sec_id
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_source_context_404_null_chunk_id(test_db):
    """GET /flashcards/{id}/source-context returns 404 when flashcard.chunk_id is null."""
    _, factory, _ = test_db
    card_id = "card-sc-no-chunk"

    async with factory() as session:
        session.add(_make_flashcard(card_id, chunk_id=None))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{card_id}/source-context")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_source_context_404_chunk_no_section(test_db):
    """GET /flashcards/{id}/source-context returns 404 when chunk.section_id is null."""
    _, factory, _ = test_db
    doc_id = "doc-sc-ns"
    chunk_id = "chunk-sc-ns"
    card_id = "card-sc-ns"

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id, section_id=None))
        session.add(_make_flashcard(card_id, doc_id, chunk_id=chunk_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{card_id}/source-context")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_source_context_404_section_not_found(test_db):
    """GET /flashcards/{id}/source-context returns 404 when section_id not in SectionModel."""
    _, factory, _ = test_db
    doc_id = "doc-sc-ns2"
    chunk_id = "chunk-sc-ns2"
    card_id = "card-sc-ns2"

    async with factory() as session:
        session.add(_make_doc(doc_id))
        # chunk has a section_id but no corresponding SectionModel row
        session.add(_make_chunk(chunk_id, doc_id, section_id="nonexistent-section"))
        session.add(_make_flashcard(card_id, doc_id, chunk_id=chunk_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{card_id}/source-context")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_source_context_404_flashcard_not_found(test_db):
    """GET /flashcards/{id}/source-context returns 404 for unknown card_id."""
    _, factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{str(uuid.uuid4())}/source-context")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_source_context_preview_truncated_at_400_chars(test_db):
    """section_preview in response is truncated to 400 chars when section.preview is longer."""
    _, factory, _ = test_db
    doc_id = "doc-sc-trunc"
    sec_id = "sec-sc-trunc"
    chunk_id = "chunk-sc-trunc"
    card_id = "card-sc-trunc"
    long_preview = "A" * 500

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(sec_id, doc_id, preview=long_preview))
        session.add(_make_chunk(chunk_id, doc_id, section_id=sec_id))
        session.add(_make_flashcard(card_id, doc_id, chunk_id=chunk_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{card_id}/source-context")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["section_preview"]) == 400
    assert data["section_preview"] == "A" * 400
