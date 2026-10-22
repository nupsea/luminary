"""Deleting a document keeps its notes unless the user asks for them to go too.

A user deleting a book from the reader lost three notes with it, one of 8,289
characters. Notes are the user's own writing, so the default detaches them: they
become standalone notes, and neither search index may keep pointing at the
deleted document. Asked to delete them, nothing of them may stay findable.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import app.services.vector_store as vs_module
from app.main import app
from app.models import (
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    NoteModel,
    NoteSourceModel,
)
from app.services.notes_service import fts_insert
from app.services.vector_store import EMBEDDING_DIM, get_lancedb_service
from tests.factories import make_document, make_note


@pytest.fixture
def lancedb(memory_db):
    saved = vs_module._lancedb_service
    vs_module._lancedb_service = None
    yield get_lancedb_service()
    vs_module._lancedb_service = saved


async def _seed(memory_db, lancedb) -> tuple[str, str, str]:
    doc_id, note_id, col_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    content = "Iceberg is a table layer over object files"
    async with memory_db.factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="No Lock-In",
                format="pdf",
                content_type="tech_book",
                file_path=f"/nonexistent/{doc_id}.pdf",
            )
        )
        session.add(
            make_note(id=note_id, document_id=doc_id, section_id=str(uuid.uuid4()), content=content)
        )
        session.add(NoteSourceModel(note_id=note_id, document_id=doc_id))
        session.add(CollectionModel(id=col_id, name="No Lock-In", auto_document_id=doc_id))
        session.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()), collection_id=col_id, member_id=note_id, member_type="note"
            )
        )
        await fts_insert(note_id, content, doc_id, session)
        await session.commit()
    lancedb.upsert_note_vector(note_id, doc_id, content, [0.1] * EMBEDDING_DIM)
    return doc_id, note_id, col_id


async def _delete(path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(path)
    assert resp.status_code == 204, resp.text


def _note_vector_doc_ids(lancedb, note_id: str) -> list[str]:
    rows = lancedb._get_or_create_note_table().to_arrow().to_pylist()
    return [r["document_id"] for r in rows if r["note_id"] == note_id]


async def _fts_doc_ids(session, note_id: str) -> list[str]:
    rows = await session.execute(
        text("SELECT document_id FROM notes_fts WHERE note_id = :nid"), {"nid": note_id}
    )
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_deleting_a_document_keeps_its_notes_as_standalone(memory_db, lancedb):
    doc_id, note_id, col_id = await _seed(memory_db, lancedb)

    await _delete(f"/documents/{doc_id}")

    async with memory_db.factory() as session:
        note = await session.get(NoteModel, note_id)
        assert note is not None, "the note was deleted with its document"
        assert (note.document_id, note.section_id, note.chunk_id) == (None, None, None)
        assert await session.get(DocumentModel, doc_id) is None
        sources = (await session.execute(select(NoteSourceModel))).scalars().all()
        assert sources == []
        assert await _fts_doc_ids(session, note_id) == [""]
        col = await session.get(CollectionModel, col_id)
        assert col is not None and col.auto_document_id is None, (
            "the book's collection keeps grouping its surviving notes"
        )
    assert _note_vector_doc_ids(lancedb, note_id) == [""]


@pytest.mark.asyncio
async def test_deleting_a_document_with_its_notes_leaves_nothing_findable(memory_db, lancedb):
    doc_id, note_id, col_id = await _seed(memory_db, lancedb)

    await _delete(f"/documents/{doc_id}?delete_notes=true")

    async with memory_db.factory() as session:
        assert await session.get(NoteModel, note_id) is None
        assert await _fts_doc_ids(session, note_id) == []
        members = (await session.execute(select(CollectionMemberModel))).scalars().all()
        assert members == []
        assert await session.get(CollectionModel, col_id) is None
    assert _note_vector_doc_ids(lancedb, note_id) == []


@pytest.mark.asyncio
async def test_bulk_delete_keeps_notes_unless_asked(memory_db, lancedb):
    doc_id, note_id, _ = await _seed(memory_db, lancedb)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/documents/bulk-delete", json={"ids": [doc_id]})
    assert resp.status_code == 200, resp.text

    async with memory_db.factory() as session:
        note = await session.get(NoteModel, note_id)
        assert note is not None and note.document_id is None
