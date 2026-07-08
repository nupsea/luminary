"""Collection flashcard management: collection-scoped search covers both
document- and note-sourced cards, and DELETE /flashcards/collection/{id}
removes exactly that set."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import CollectionMemberModel, CollectionModel, FlashcardModel


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _card(cid: str, *, document_id=None, note_id=None, source="document", deck="default"):
    return FlashcardModel(
        id=cid, question=f"Q {cid}?", answer="A real multi-word answer here.",
        source_excerpt="s", document_id=document_id, note_id=note_id,
        source=source, deck=deck,
    )


async def _seed(factory) -> str:
    coll_id = str(uuid.uuid4())
    doc_id, note_id, other_doc = "doc-in", "note-in", "doc-out"
    async with factory() as s:
        s.add(CollectionModel(id=coll_id, name="Data Architecture", color="#6366F1", sort_order=0))
        s.add(CollectionMemberModel(
            id=str(uuid.uuid4()), collection_id=coll_id, member_id=doc_id, member_type="document"))
        s.add(CollectionMemberModel(
            id=str(uuid.uuid4()), collection_id=coll_id, member_id=note_id, member_type="note"))
        s.add(_card("c-doc", document_id=doc_id))
        s.add(_card("c-note", note_id=note_id, source="note", deck="Data Architecture"))
        s.add(_card("c-outside", document_id=other_doc))
        await s.commit()
    return coll_id


@pytest.mark.asyncio
async def test_collection_search_includes_document_and_note_cards(test_db):
    coll_id = await _seed(test_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/flashcards/search", params={"collection_id": coll_id})
        assert resp.status_code == 200
        ids = {c["id"] for c in resp.json()["items"]}
        assert ids == {"c-doc", "c-note"}  # document + note cards, not the outsider


@pytest.mark.asyncio
async def test_delete_all_collection_flashcards(test_db):
    coll_id = await _seed(test_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/flashcards/collection/{coll_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

        # collection cards gone, the outsider survives
        remaining = (await client.get("/flashcards/search", params={"collection_id": coll_id}))
        assert remaining.json()["items"] == []
        outsider = await client.get("/flashcards/search", params={"document_id": "doc-out"})
        assert {c["id"] for c in outsider.json()["items"]} == {"c-outside"}


@pytest.mark.asyncio
async def test_delete_empty_collection_is_noop(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/flashcards/collection/{uuid.uuid4()}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0
