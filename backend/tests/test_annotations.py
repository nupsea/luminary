"""Tests for POST /annotations, GET /annotations, DELETE /annotations/{id}."""

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_annotation(test_db):
    """POST /annotations -> 201, returns id, section_id, color, created_at."""
    from httpx import ASGITransport, AsyncClient

    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/annotations",
            json={
                "document_id": doc_id,
                "section_id": sec_id,
                "selected_text": "hello world",
                "start_offset": 0,
                "end_offset": 11,
                "color": "yellow",
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["document_id"] == doc_id
    assert data["section_id"] == sec_id
    assert data["selected_text"] == "hello world"
    assert data["color"] == "yellow"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_annotations_by_document(test_db):
    """GET /annotations?document_id=A returns only annotations for doc A."""
    from httpx import ASGITransport, AsyncClient

    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create 2 annotations for doc A, 1 for doc B
        for _ in range(2):
            await client.post(
                "/annotations",
                json={
                    "document_id": doc_a,
                    "section_id": sec_id,
                    "selected_text": "text A",
                    "start_offset": 0,
                    "end_offset": 6,
                    "color": "green",
                },
            )
        await client.post(
            "/annotations",
            json={
                "document_id": doc_b,
                "section_id": sec_id,
                "selected_text": "text B",
                "start_offset": 0,
                "end_offset": 6,
                "color": "blue",
            },
        )

        resp = await client.get(f"/annotations?document_id={doc_a}")

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert all(i["document_id"] == doc_a for i in items)


@pytest.mark.asyncio
async def test_delete_annotation(test_db):
    """DELETE /annotations/{id} -> 204; subsequent GET returns empty list."""
    from httpx import ASGITransport, AsyncClient

    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/annotations",
            json={
                "document_id": doc_id,
                "section_id": sec_id,
                "selected_text": "to delete",
                "start_offset": 0,
                "end_offset": 9,
                "color": "pink",
            },
        )
        assert create_resp.status_code == 201
        ann_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/annotations/{ann_id}")
        assert del_resp.status_code == 204

        list_resp = await client.get(f"/annotations?document_id={doc_id}")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_annotation_404(test_db):
    """DELETE /annotations/{nonexistent} -> 404."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/annotations/does-not-exist")

    assert resp.status_code == 404
