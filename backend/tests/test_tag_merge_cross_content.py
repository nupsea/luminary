"""Tag merge across notes and documents — option (b) slice 3."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, NoteModel
from app.services.notes_service import sync_tag_index


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
        title="Doc",
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=[],
    )


@pytest.mark.anyio
async def test_merge_rewrites_both_notes_and_documents(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())
    src = f"bio-{uuid.uuid4().hex[:6]}"
    tgt = f"biology-{uuid.uuid4().hex[:6]}"

    # Seed both note and doc directly to avoid the embed background task that
    # POST /notes kicks off (it races with the merge under concurrent
    # in-memory SQLite test ordering).
    async with factory() as s:
        s.add(_make_doc(doc_id))
        now = datetime.now(UTC)
        s.add(
            NoteModel(
                id=note_id,
                content="n",
                tags=[src],
                document_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        await s.flush()
        await sync_tag_index(note_id, [src], s)
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        d_resp = await c.patch(f"/documents/{doc_id}/tags", json={"tags": [src]})
        assert d_resp.status_code == 200

        # Create the target canonical tag (source already exists via the writes above).
        await c.post("/tags", json={"id": tgt, "display_name": tgt})

        m_resp = await c.post(
            "/tags/merge", json={"source_tag_id": src, "target_tag_id": tgt}
        )
        assert m_resp.status_code == 200, m_resp.text
        body = m_resp.json()
        assert body["affected_notes"] == 1
        assert body["affected_documents"] == 1

        n_get = await c.get(f"/notes/{note_id}")
        assert tgt in n_get.json()["tags"]
        assert src not in n_get.json()["tags"]

        r_new = (await c.get(f"/documents?tag={tgt}")).json()
        assert doc_id in [d["id"] for d in r_new["items"]]
        r_old = (await c.get(f"/documents?tag={src}")).json()
        assert doc_id not in [d["id"] for d in r_old["items"]]
