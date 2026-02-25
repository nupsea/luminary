"""Tests for GET /documents, PATCH /documents/{id}, DELETE /documents/{id}."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    StudySessionModel,
    SummaryModel,
)

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
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


# ---------------------------------------------------------------------------
# Unit tests for learning_status derivation
# ---------------------------------------------------------------------------


def test_derive_learning_status_not_started():
    from app.routers.documents import _derive_learning_status

    assert _derive_learning_status(0, 0, 0) == "not_started"


def test_derive_learning_status_summarized():
    from app.routers.documents import _derive_learning_status

    assert _derive_learning_status(0, 0, 1) == "summarized"


def test_derive_learning_status_flashcards_generated():
    from app.routers.documents import _derive_learning_status

    assert _derive_learning_status(0, 3, 1) == "flashcards_generated"


def test_derive_learning_status_studied():
    from app.routers.documents import _derive_learning_status

    assert _derive_learning_status(1, 3, 1) == "studied"


# ---------------------------------------------------------------------------
# GET /documents endpoint tests
# ---------------------------------------------------------------------------


async def test_list_documents_empty(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


async def test_list_documents_returns_basic_fields(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, title="My Paper", content_type="paper"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["id"] == doc_id
    assert item["title"] == "My Paper"
    assert item["content_type"] == "paper"
    assert item["flashcard_count"] == 0
    assert item["summary_one_sentence"] is None
    assert item["learning_status"] == "not_started"
    assert "tags" in item


async def test_list_documents_learning_status_not_started(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.json()["items"][0]["learning_status"] == "not_started"


async def test_list_documents_learning_status_summarized(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="executive",
                content="Summary content.",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.json()["items"][0]["learning_status"] == "summarized"


async def test_list_documents_learning_status_flashcards_generated(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                chunk_id=str(uuid.uuid4()),
                question="Q?",
                answer="A.",
                source_excerpt="excerpt",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    item = resp.json()["items"][0]
    assert item["learning_status"] == "flashcards_generated"
    assert item["flashcard_count"] == 1


async def test_list_documents_learning_status_studied(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            StudySessionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="flashcard",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.json()["items"][0]["learning_status"] == "studied"


async def test_list_documents_summary_one_sentence_populated(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="one_sentence",
                content="Short summary.",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.json()["items"][0]["summary_one_sentence"] == "Short summary."


async def test_list_documents_filter_by_content_type(test_db):
    """content_type query param filters to matching documents only."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_make_doc(content_type="book"))
        session.add(_make_doc(content_type="paper"))
        session.add(_make_doc(content_type="notes"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents?content_type=book,paper")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    types = {item["content_type"] for item in data["items"]}
    assert types == {"book", "paper"}


async def test_list_documents_filter_by_tag(test_db):
    """tag query param filters to documents with that tag."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_make_doc(tags=["ai", "ml"]))
        session.add(_make_doc(tags=["history"]))
        session.add(_make_doc(tags=[]))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents?tag=ai")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert "ai" in data["items"][0]["tags"]


async def test_list_documents_pagination(test_db):
    """page and page_size params return the correct slice."""
    _, factory, _ = test_db
    async with factory() as session:
        for i in range(5):
            session.add(_make_doc(title=f"Doc {i}"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents?page=1&page_size=2")
    data = resp.json()
    assert data["total"] == 5
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) == 2

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp2 = await client.get("/documents?page=3&page_size=2")
    data2 = resp2.json()
    assert len(data2["items"]) == 1  # 5 docs, page 3 of size 2 → 1 item


# ---------------------------------------------------------------------------
# PATCH /documents/{id} endpoint tests
# ---------------------------------------------------------------------------


async def test_patch_document_title(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, title="Old Title"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/documents/{doc_id}", json={"title": "New Title"})
    assert resp.status_code == 200

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None
    assert doc.title == "New Title"


async def test_patch_document_tags(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/documents/{doc_id}", json={"tags": ["ai", "research"]})
    assert resp.status_code == 200

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None
    assert doc.tags == ["ai", "research"]


async def test_patch_document_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/documents/no-such-id", json={"title": "X"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /documents/{id} endpoint tests
# ---------------------------------------------------------------------------


async def test_delete_document_removes_doc_from_sqlite(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    mock_lancedb = MagicMock()
    with patch("app.routers.documents.get_lancedb_service", return_value=mock_lancedb):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/documents/{doc_id}")
    assert resp.status_code == 204

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is None


async def test_delete_document_removes_child_rows(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                text="Some chunk text",
                chunk_index=0,
            )
        )
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="one_sentence",
                content="A summary.",
            )
        )
        await session.commit()

    mock_lancedb = MagicMock()
    with patch("app.routers.documents.get_lancedb_service", return_value=mock_lancedb):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.delete(f"/documents/{doc_id}")

    async with factory() as session:
        chunks = (
            await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id))
        ).scalars().all()
        summaries = (
            await session.execute(select(SummaryModel).where(SummaryModel.document_id == doc_id))
        ).scalars().all()
    assert chunks == []
    assert summaries == []


async def test_delete_document_calls_lancedb(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    mock_lancedb = MagicMock()
    with patch("app.routers.documents.get_lancedb_service", return_value=mock_lancedb):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/documents/{doc_id}")

    assert resp.status_code == 204
    mock_lancedb.delete_document.assert_called_once_with(doc_id)


async def test_delete_document_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/documents/no-such-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /documents/bulk-delete endpoint tests
# ---------------------------------------------------------------------------


async def test_bulk_delete_removes_docs(test_db):
    """POST /documents/bulk-delete removes all listed documents."""
    _, factory, _ = test_db
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(id1))
        session.add(_make_doc(id2))
        await session.commit()

    mock_lancedb = MagicMock()
    with patch("app.routers.documents.get_lancedb_service", return_value=mock_lancedb):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/documents/bulk-delete", json={"ids": [id1, id2]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert set(data["deleted"]) == {id1, id2}

    async with factory() as session:
        doc1 = await session.get(DocumentModel, id1)
        doc2 = await session.get(DocumentModel, id2)
    assert doc1 is None
    assert doc2 is None


async def test_bulk_delete_skips_missing(test_db):
    """POST /documents/bulk-delete silently skips IDs that don't exist."""
    _, factory, _ = test_db
    real_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(real_id))
        await session.commit()

    mock_lancedb = MagicMock()
    with patch("app.routers.documents.get_lancedb_service", return_value=mock_lancedb):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/bulk-delete", json={"ids": [real_id, "nonexistent-id"]}
            )

    assert resp.status_code == 200
    assert resp.json()["count"] == 1


# ---------------------------------------------------------------------------
# PATCH /documents/{id}/tags endpoint tests
# ---------------------------------------------------------------------------


async def test_patch_tags_endpoint(test_db):
    """PATCH /documents/{id}/tags replaces the tag list."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, tags=["old"]))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/documents/{doc_id}/tags", json={"tags": ["new", "tags"]})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["new", "tags"]

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None
    assert doc.tags == ["new", "tags"]


async def test_patch_tags_endpoint_404(test_db):
    """PATCH /documents/{id}/tags returns 404 for unknown document."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/documents/no-such-id/tags", json={"tags": ["x"]})
    assert resp.status_code == 404
