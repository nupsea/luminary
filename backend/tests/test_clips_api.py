"""Unit tests for POST/GET/PATCH/DELETE /clips endpoints (S150)."""

from __future__ import annotations

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
async def test_create_clip(test_db) -> None:
    """POST /clips creates a row and returns 201 with all fields."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/clips",
            json={
                "document_id": "doc-abc",
                "section_id": "sec-1",
                "section_heading": "Chapter 1",
                "selected_text": "A great passage about monads.",
                "user_note": "",
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["document_id"] == "doc-abc"
    assert body["selected_text"] == "A great passage about monads."
    assert body["section_heading"] == "Chapter 1"
    assert body["user_note"] == ""
    assert "id" in body


@pytest.mark.asyncio
async def test_get_clips_returns_created(test_db) -> None:
    """GET /clips returns the clip just created."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/clips",
            json={
                "document_id": "doc-get",
                "selected_text": "Another passage.",
            },
        )
        assert create_resp.status_code == 201
        clip_id = create_resp.json()["id"]

        list_resp = await client.get("/clips")
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert clip_id in ids


@pytest.mark.asyncio
async def test_get_clips_filtered_by_document(test_db) -> None:
    """GET /clips?document_id=X returns only clips for that document."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/clips",
            json={"document_id": "doc-filter-a", "selected_text": "Passage A."},
        )
        await client.post(
            "/clips",
            json={"document_id": "doc-filter-b", "selected_text": "Passage B."},
        )

        resp = await client.get("/clips?document_id=doc-filter-a")
    assert resp.status_code == 200
    results = resp.json()
    assert all(c["document_id"] == "doc-filter-a" for c in results)
    texts = [c["selected_text"] for c in results]
    assert "Passage A." in texts


@pytest.mark.asyncio
async def test_patch_clip_user_note(test_db) -> None:
    """PATCH /clips/{id} updates user_note."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/clips",
            json={"document_id": "doc-patch", "selected_text": "Patchable passage."},
        )
        clip_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/clips/{clip_id}",
            json={"user_note": "My annotation note here."},
        )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["user_note"] == "My annotation note here."


@pytest.mark.asyncio
async def test_delete_clip(test_db) -> None:
    """DELETE /clips/{id} removes the clip; second DELETE returns 404."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/clips",
            json={"document_id": "doc-del", "selected_text": "Deletable passage."},
        )
        clip_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/clips/{clip_id}")
        assert del_resp.status_code == 204

        del_again = await client.delete(f"/clips/{clip_id}")
        assert del_again.status_code == 404


@pytest.mark.asyncio
async def test_patch_missing_clip_returns_404(test_db) -> None:
    """PATCH on a non-existent clip returns 404."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/clips/nonexistent-id",
            json={"user_note": "won't work"},
        )
    assert resp.status_code == 404
