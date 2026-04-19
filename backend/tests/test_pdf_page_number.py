"""Tests for S146: pdf_page_number population and PDF file endpoints.

AC1/AC2: ChunkModel.pdf_page_number added and populated during PDF ingestion.
AC3:     Unit test -- ingest 5-section PDF fixture; all chunks have pdf_page_number in [1..5].
AC4:     GET /documents/{id}/file returns 200 with Content-Type: application/pdf.
AC5:     GET /documents/{id}/file returns 404 when file not found on disk.
AC6:     GET /documents/{id}/pdf-meta returns {page_count, has_toc}.
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


def _make_doc(doc_id: str, **kwargs) -> DocumentModel:
    defaults: dict = {
        "id": doc_id,
        "title": "Test PDF",
        "format": "pdf",
        "content_type": "book",
        "word_count": 200,
        "page_count": 5,
        "file_path": "/tmp/test.pdf",
        "stage": "chunking",
        "tags": [],
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


def _make_state(doc_id: str, sections: list[dict], format: str = "pdf") -> IngestionState:
    return IngestionState(
        document_id=doc_id,
        file_path="/tmp/test.pdf",
        format=format,
        parsed_document={
            "title": "Test PDF",
            "format": format,
            "pages": len(sections),
            "word_count": sum(len(s["text"].split()) for s in sections),
            "sections": sections,
            "raw_text": " ".join(s["text"] for s in sections),
        },
        content_type="book",
        chunks=None,
        status="chunking",
        error=None,
        section_summary_count=None,
        audio_duration_seconds=None,
        _audio_chunks=None,
    )


def _make_pdf_sections(num_pages: int) -> list[dict]:
    """Create one section per page, each with enough text to produce at least one chunk."""
    return [
        {
            "heading": f"Chapter {i}",
            "level": 1,
            "text": f"Page {i} content. " * 50,  # ~100 words — enough for at least 1 chunk
            "page_start": i,
            "page_end": i,
        }
        for i in range(1, num_pages + 1)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_pdf_chunks_have_page_numbers(test_db):
    """AC3: All chunks from a 5-section PDF have pdf_page_number set to 1-based page in [1..5]."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    sections = _make_pdf_sections(5)
    state = _make_state(doc_id, sections, format="pdf")
    await _chunk_book(state, state["parsed_document"], doc_id)

    async with factory() as session:
        result = await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id))
        chunks = result.scalars().all()

    assert len(chunks) > 0, "Expected at least one chunk"
    page_numbers = {c.pdf_page_number for c in chunks}
    assert page_numbers.issubset({1, 2, 3, 4, 5}), f"Unexpected page numbers: {page_numbers}"
    assert None not in page_numbers, "pdf_page_number must not be None for PDF chunks"


async def test_txt_chunks_have_null_page_numbers(test_db):
    """Non-PDF chunks must have pdf_page_number = None."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, format="txt"))
        await session.commit()

    sections = _make_pdf_sections(3)
    state = _make_state(doc_id, sections, format="txt")
    await _chunk_book(state, state["parsed_document"], doc_id)

    async with factory() as session:
        result = await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id))
        chunks = result.scalars().all()

    assert len(chunks) > 0, "Expected at least one chunk"
    for c in chunks:
        assert c.pdf_page_number is None, (
            f"Non-PDF chunk should have pdf_page_number=None, got {c.pdf_page_number}"
        )


async def test_serve_document_file_200(test_db):
    """AC4: GET /documents/{id}/file returns 200 + Content-Type: application/pdf for PDF."""
    _, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    # Write a minimal real-looking PDF bytes to disk
    pdf_path = tmp_path / f"{doc_id}.pdf"
    # Minimal valid PDF structure (parseable bytes)
    pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")

    async with factory() as session:
        session.add(_make_doc(doc_id, file_path=str(pdf_path)))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/file")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")


async def test_serve_document_file_404_not_on_disk(test_db):
    """AC5: GET /documents/{id}/file returns 404 when file path does not exist on disk."""
    _, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, file_path="/nonexistent/path/to/doc.pdf"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/file")

    assert resp.status_code == 404


async def test_serve_document_file_404_no_document(test_db):
    """GET /documents/{id}/file returns 404 when document not in DB."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{uuid.uuid4()}/file")

    assert resp.status_code == 404


async def test_get_pdf_meta_200(test_db):
    """AC6: GET /documents/{id}/pdf-meta returns {page_count, has_toc: true} for PDF."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, page_count=42))
        # Add 2 sections so has_toc=True
        for i in range(2):
            session.add(
                SectionModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    heading=f"Section {i}",
                    level=1,
                    page_start=i + 1,
                    page_end=i + 1,
                    section_order=i,
                    preview="",
                )
            )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/pdf-meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["page_count"] == 42
    assert data["has_toc"] is True


async def test_get_pdf_meta_no_toc(test_db):
    """AC6: GET /documents/{id}/pdf-meta returns has_toc=False when no sections exist."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, page_count=10))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/pdf-meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["page_count"] == 10
    assert data["has_toc"] is False


async def test_get_pdf_meta_400_non_pdf(test_db):
    """AC6: GET /documents/{id}/pdf-meta returns 400 for non-PDF documents."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, format="txt", file_path="/tmp/test.txt"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/pdf-meta")

    assert resp.status_code == 400


async def test_get_pdf_meta_404_not_found(test_db):
    """GET /documents/{id}/pdf-meta returns 404 for unknown document ID."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{uuid.uuid4()}/pdf-meta")

    assert resp.status_code == 404
