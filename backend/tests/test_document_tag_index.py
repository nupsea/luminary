"""Tests for DocumentTagIndexModel + sync_document_tag_index — option (b) slice 1."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import CanonicalTagModel, DocumentModel, DocumentTagIndexModel


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

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _make_doc(doc_id: str, **kw) -> DocumentModel:
    defaults = dict(
        id=doc_id,
        title="Doc",
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=[],
    )
    defaults.update(kw)
    return DocumentModel(**defaults)


async def _tags_in_index(factory, doc_id: str) -> set[str]:
    async with factory() as s:
        rows = (
            await s.execute(
                select(DocumentTagIndexModel.tag_full).where(
                    DocumentTagIndexModel.document_id == doc_id
                )
            )
        ).all()
    return {r[0] for r in rows}


async def _canonical_count(factory, tag: str) -> int:
    async with factory() as s:
        v = (
            await s.execute(
                select(CanonicalTagModel.usage_count).where(CanonicalTagModel.id == tag)
            )
        ).scalar_one_or_none()
    return v or 0


@pytest.mark.anyio
async def test_patch_doc_tags_populates_index(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["physics", "science/biology"]},
        )
        assert r.status_code == 200

    assert await _tags_in_index(factory, doc_id) == {"physics", "science/biology"}
    assert await _canonical_count(factory, "physics") == 1
    assert await _canonical_count(factory, "science/biology") == 1


@pytest.mark.anyio
async def test_patch_doc_tags_diffs_old_vs_new(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["a", "b"]})
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["b", "c"]})

    assert await _tags_in_index(factory, doc_id) == {"b", "c"}
    assert await _canonical_count(factory, "a") == 0
    assert await _canonical_count(factory, "b") == 1
    assert await _canonical_count(factory, "c") == 1


@pytest.mark.anyio
async def test_doc_deletion_clears_index_and_decrements(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["alpha"]})
        assert await _canonical_count(factory, "alpha") == 1
        r = await c.delete(f"/documents/{doc_id}")
        assert r.status_code == 204

    assert await _tags_in_index(factory, doc_id) == set()
    assert await _canonical_count(factory, "alpha") == 0


@pytest.mark.anyio
async def test_canonical_count_combines_notes_and_documents(test_db):
    """A tag used by one note and one document has usage_count == 2."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["shared"]})
        note_resp = await c.post(
            "/notes",
            json={"content": "n", "tags": ["shared"], "document_id": None},
        )
        assert note_resp.status_code == 201

    assert await _canonical_count(factory, "shared") == 2
