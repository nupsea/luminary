"""Tests for POST /reading/progress and reading_progress_pct in GET /documents/{id}."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, SectionModel

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


def _make_doc(doc_id: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Reading Test Doc",
        format="txt",
        content_type="book",
        word_count=500,
        page_count=10,
        file_path="/tmp/reading_test.txt",
        stage="complete",
    )


def _make_section(doc_id: str, section_id: str | None = None, order: int = 0) -> SectionModel:
    return SectionModel(
        id=section_id or str(uuid.uuid4()),
        document_id=doc_id,
        heading=f"Section {order}",
        level=1,
        page_start=order,
        page_end=order + 1,
        section_order=order,
        preview="",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_record(test_db):
    """First POST creates a record with view_count=1."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/reading/progress",
            json={"document_id": doc_id, "section_id": "sec-001"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["view_count"] == 1
    assert data["document_id"] == doc_id
    assert data["section_id"] == "sec-001"


@pytest.mark.asyncio
async def test_upsert_increments_view_count(test_db):
    """Two POSTs for the same (doc, section) -> view_count=2."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/reading/progress",
            json={"document_id": doc_id, "section_id": "sec-002"},
        )
        resp = await client.post(
            "/reading/progress",
            json={"document_id": doc_id, "section_id": "sec-002"},
        )
    assert resp.status_code == 200
    assert resp.json()["view_count"] == 2


@pytest.mark.asyncio
async def test_upsert_404_for_missing_doc(test_db):
    """POST /reading/progress returns 404 for an unknown document_id."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/reading/progress",
            json={"document_id": "does-not-exist", "section_id": "sec-x"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reading_progress_pct_in_document_detail(test_db):
    """reading_progress_pct in GET /documents/{id} reflects correct ratio."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    sec1_id = str(uuid.uuid4())
    sec2_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, sec1_id, order=0))
        session.add(_make_section(doc_id, sec2_id, order=1))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Mark 1 of 2 sections as read
        await client.post(
            "/reading/progress",
            json={"document_id": doc_id, "section_id": sec1_id},
        )
        resp = await client.get(f"/documents/{doc_id}")

    assert resp.status_code == 200
    pct = resp.json()["reading_progress_pct"]
    assert abs(pct - 0.5) < 0.01  # 1/2 sections read


@pytest.mark.asyncio
async def test_reading_progress_pct_zero_for_unread_document(test_db):
    """GET /documents/{id} returns reading_progress_pct=0.0 for unread doc."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, order=0))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}")

    assert resp.status_code == 200
    assert resp.json()["reading_progress_pct"] == 0.0
