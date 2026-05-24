"""GET /tags?scope=document|note|all (Release B)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel


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


def _make_doc(doc_id: str) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="d",
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=[],
    )


@pytest.mark.anyio
async def test_scope_document_excludes_note_only_tags(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # 'physics' lives only on a note; 'history' lives only on a doc.
        await c.post(
            "/notes",
            json={"content": "a note about physics", "tags": ["physics"], "document_id": None},
        )
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["history"]})

        all_resp = (await c.get("/tags?scope=all")).json()
        all_ids = {t["id"] for t in all_resp}
        assert {"physics", "history"} <= all_ids

        doc_resp = (await c.get("/tags?scope=document")).json()
        doc_ids = {t["id"] for t in doc_resp}
        assert "history" in doc_ids
        assert "physics" not in doc_ids

        note_resp = (await c.get("/tags?scope=note")).json()
        note_ids = {t["id"] for t in note_resp}
        assert "physics" in note_ids
        assert "history" not in note_ids


@pytest.mark.anyio
async def test_scope_limit_caps_results(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["a", "b", "c", "d", "e"]},
        )
        resp = (await c.get("/tags?scope=document&limit=2")).json()
        assert len(resp) == 2


@pytest.mark.anyio
async def test_scope_unknown_value_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/tags?scope=hyperlink")
        assert r.status_code == 422
