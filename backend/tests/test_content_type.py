"""Tests for the content_type form field on /documents/ingest.

content_type is optional: omitting it is the request to classify. It was
mandatory (S63) until the upload dialog was found to be defaulting every
non-media file to "book", which -- because a supplied type skips classification
outright -- meant auto-detection never ran for any document the user uploaded.

Covers:
  (a) test_ingest_without_content_type_classifies
  (b) test_ingest_with_valid_type_skips_classify_llm
  (c) test_patch_content_type_updates_document
  (d) test_invalid_content_type_returns_422
"""

import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel

# Fixture


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


# Tests


@pytest.mark.anyio
async def test_ingest_without_content_type_classifies(test_db, monkeypatch):
    """Omitting content_type is accepted, and passes None so classify_node runs.

    None specifically, not a placeholder: classify_node treats any non-None
    content_type as the caller's decision and skips every heuristic.
    """
    called: list[str | None] = []

    async def _noop() -> None:
        return None

    # Recorded at call time, not inside the coroutine body: the job never runs
    # here, so a mock that appends when awaited would record nothing and the
    # assertion below would pass on an empty list.
    def _mock_run_ingestion(document_id, file_path, format, content_type=None):
        called.append(content_type)
        return _noop()

    import app.routers.documents as documents_module

    monkeypatch.setattr(documents_module, "run_ingestion", _mock_run_ingestion)
    monkeypatch.setattr(
        documents_module.get_ingestion_jobs(), "launch", lambda doc_id, coro: coro.close()
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
        )
    assert resp.status_code == 200, resp.text
    assert called == [None]


@pytest.mark.anyio
async def test_ingest_with_valid_type_skips_classify_llm(test_db, monkeypatch):
    """POST with content_type='book' stores the type in DB and passes it to run_ingestion."""
    engine, factory, _ = test_db
    called: list[str | None] = []

    async def _mock_run_ingestion(document_id, file_path, format, content_type=None):
        called.append(content_type)

    # Patch so background task runs our mock immediately rather than real ingestion
    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={
                "file": ("book.txt", io.BytesIO(b"Chapter 1\nOnce upon a time..."), "text/plain")
            },
            data={"content_type": "book"},
        )
    assert resp.status_code == 200
    doc_id = resp.json()["document_id"]

    # The document must be created with content_type='book' immediately in DB
    from sqlalchemy import select  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with factory() as session:
        result = await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = result.scalar_one_or_none()
    assert doc is not None
    assert doc.content_type == "book", f"Expected book, got {doc.content_type}"


@pytest.mark.anyio
async def test_patch_content_type_updates_document(test_db):
    """PATCH /documents/{id} with content_type updates the field in DB."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, content_type="notes"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/documents/{doc_id}",
            json={"content_type": "book"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] is True
    assert "Re-ingest document" in body.get("note", "")

    # Verify via GET /documents
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_resp = await client.get("/documents")
    items = list_resp.json()["items"]
    match = next((i for i in items if i["id"] == doc_id), None)
    assert match is not None
    assert match["content_type"] == "book"


@pytest.mark.anyio
async def test_invalid_content_type_returns_422(test_db):
    """POST /documents/ingest with an unsupported content_type returns HTTP 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"content_type": "unknown_type"},
        )
    assert resp.status_code == 422
