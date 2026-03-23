"""Unit tests for POST/GET /documents/{id}/position endpoints (S152)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app

# ---------------------------------------------------------------------------
# Test DB fixture
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


async def _create_document(doc_id: str) -> None:
    """Insert a minimal document row so position endpoints can verify existence."""
    from app.models import DocumentModel

    factory = db_module._session_factory
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Book",
                format="txt",
                content_type="notes",
                word_count=0,
                page_count=0,
                file_path="/tmp/noop.txt",
                stage="complete",
                tags=[],
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_single_row(test_db) -> None:
    """POST /position twice with different page numbers; DB has exactly one row with latest page."""
    from httpx import ASGITransport, AsyncClient

    doc_id = str(uuid.uuid4())
    await _create_document(doc_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            f"/documents/{doc_id}/position",
            json={
                "last_section_id": "sec-1",
                "last_section_heading": "Chapter 1",
                "last_pdf_page": 10,
            },
        )
        assert r1.status_code == 200
        assert r1.json()["last_pdf_page"] == 10

        r2 = await client.post(
            f"/documents/{doc_id}/position",
            json={
                "last_section_id": "sec-5",
                "last_section_heading": "Chapter 5",
                "last_pdf_page": 42,
            },
        )
        assert r2.status_code == 200
        assert r2.json()["last_pdf_page"] == 42
        assert r2.json()["last_section_heading"] == "Chapter 5"

    # Verify exactly one row in the DB
    from sqlalchemy import select

    from app.models import ReadingPositionModel

    factory = db_module._session_factory
    async with factory() as session:
        rows = (await session.execute(select(ReadingPositionModel))).scalars().all()
    assert len(rows) == 1
    assert rows[0].last_pdf_page == 42
    assert rows[0].last_section_heading == "Chapter 5"


@pytest.mark.asyncio
async def test_get_position_returns_404_for_no_record(test_db) -> None:
    """GET /position returns 404 when no position has been saved for the document."""
    from httpx import ASGITransport, AsyncClient

    doc_id = str(uuid.uuid4())
    await _create_document(doc_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/documents/{doc_id}/position")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_position_returns_saved_record(test_db) -> None:
    """GET /position returns the record written by a prior POST."""
    from httpx import ASGITransport, AsyncClient

    doc_id = str(uuid.uuid4())
    await _create_document(doc_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            f"/documents/{doc_id}/position",
            json={
                "last_section_id": "sec-7",
                "last_section_heading": "Metacircular Evaluator",
                "last_pdf_page": 99,
                "last_epub_chapter_index": None,
            },
        )
        r = await client.get(f"/documents/{doc_id}/position")

    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == doc_id
    assert body["last_section_id"] == "sec-7"
    assert body["last_section_heading"] == "Metacircular Evaluator"
    assert body["last_pdf_page"] == 99
    assert body["last_epub_chapter_index"] is None


@pytest.mark.asyncio
async def test_post_position_returns_404_for_missing_doc(test_db) -> None:
    """POST /position returns 404 when the document does not exist."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/documents/nonexistent-doc-id/position",
            json={"last_section_id": "sec-1", "last_section_heading": "Intro"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_position_returns_404_for_missing_doc(test_db) -> None:
    """GET /position returns 404 when the document itself does not exist."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/documents/nonexistent-doc-id/position")
    assert r.status_code == 404
