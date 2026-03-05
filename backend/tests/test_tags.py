"""Tests for tag storage, retrieval, and filtering (S62)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel

# ---------------------------------------------------------------------------
# Fixture
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


def _make_doc(doc_id: str | None = None, **kwargs) -> DocumentModel:
    defaults = {
        "id": doc_id or str(uuid.uuid4()),
        "title": "Test Doc",
        "format": "txt",
        "content_type": "notes",
        "word_count": 100,
        "page_count": 1,
        "file_path": "/tmp/test.txt",
        "stage": "complete",
        "tags": [],
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_patch_tags_stores_list(test_db):
    """PATCH /documents/{id}/tags stores tags as a JSON list; GET returns list[str]."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, tags=[]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        patch_resp = await client.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["physics", "science"]},
        )
        assert patch_resp.status_code == 200
        body = patch_resp.json()
        assert isinstance(body["tags"], list)
        assert body["tags"] == ["physics", "science"]

        # GET /documents and verify tags appear as list[str]
        list_resp = await client.get("/documents")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        match = next((i for i in items if i["id"] == doc_id), None)
        assert match is not None
        assert isinstance(match["tags"], list)
        assert match["tags"] == ["physics", "science"]


@pytest.mark.anyio
async def test_tag_filter_returns_matching_docs(test_db):
    """GET /documents?tag=X returns only documents whose tag list includes X."""
    engine, factory, _ = test_db
    doc_physics = str(uuid.uuid4())
    doc_history = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_physics, title="Physics Book", tags=["physics"]))
        session.add(_make_doc(doc_history, title="History Book", tags=["history"]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/documents?tag=physics")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = [i["id"] for i in items]
        assert doc_physics in ids
        assert doc_history not in ids


@pytest.mark.anyio
async def test_tag_filter_no_substring_collision(test_db):
    """GET /documents?tag=bio must NOT match a doc tagged 'biology' (exact element only)."""
    engine, factory, _ = test_db
    doc_bio = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_bio, title="Biology Book", tags=["biology"]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/documents?tag=bio")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = [i["id"] for i in items]
        # 'bio' is a substring of 'biology' but must NOT match as an element
        assert doc_bio not in ids


@pytest.mark.anyio
async def test_patch_tags_replaces_not_appends(test_db):
    """Second PATCH replaces the tag list entirely, not appends."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, tags=["old-tag"]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # First patch
        await client.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["first"]},
        )
        # Second patch replaces
        patch2 = await client.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["second"]},
        )
        assert patch2.status_code == 200
        assert patch2.json()["tags"] == ["second"]

        # Verify via GET /documents
        list_resp = await client.get("/documents")
        match = next((i for i in list_resp.json()["items"] if i["id"] == doc_id), None)
        assert match is not None
        assert match["tags"] == ["second"]
        assert "first" not in match["tags"]
        assert "old-tag" not in match["tags"]
