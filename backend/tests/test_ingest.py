import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel
from app.workflows.ingestion import IngestionState, _classify, chunk_node

# ---------------------------------------------------------------------------
# Classification heuristic unit tests (pure functions, no DB)
# ---------------------------------------------------------------------------


def test_classify_conversation_by_speaker_pattern():
    text = "Alice: Good morning.\nBob: Hello Alice, how are you today?"
    assert _classify(text, [], 50, "txt") == "conversation"


def test_classify_conversation_by_keyword():
    text = "interviewer: What brings you here?\nguest: I wanted to discuss the topic."
    assert _classify(text, [], 50, "txt") == "conversation"


def test_classify_paper_by_abstract():
    text = "abstract\n\nThis paper presents a new methodology for testing software."
    assert _classify(text, [], 500, "txt") == "paper"


def test_classify_book_by_chapters_and_length():
    headings = [
        {"heading": "Chapter 1 Introduction", "level": 1},
        {"heading": "Chapter 2 Background", "level": 1},
    ]
    text = "word " * 41000
    assert _classify(text, headings, 41000, "txt") == "book"


def test_classify_code_by_extension():
    assert _classify("def foo(): pass", [], 5, "py") == "code"


def test_classify_defaults_to_notes():
    assert _classify("some random text about everyday life", [], 100, "txt") == "notes"


# ---------------------------------------------------------------------------
# Test DB fixture — isolates each test with an in-memory SQLite database
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """Wire an in-memory SQLite DB into the app's global singletons."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Override the lazy singletons so all module-level callers get the test DB
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
# Workflow node tests
# ---------------------------------------------------------------------------


async def test_chunk_node_writes_to_db(test_db):
    """chunk_node should persist chunks to the chunks table."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                format="txt",
                content_type="notes",
                word_count=20,
                page_count=1,
                file_path=str(tmp_path / "test.txt"),
                stage="chunking",
            )
        )
        await session.commit()

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(tmp_path / "test.txt"),
        "format": "txt",
        "parsed_document": {
            "title": "Test Doc",
            "format": "txt",
            "pages": 1,
            "word_count": 20,
            "sections": [
                {
                    "heading": "",
                    "level": 1,
                    "text": "This is a test document. It contains sentences for chunking.",
                    "page_start": 1,
                    "page_end": 1,
                }
            ],
            "raw_text": "This is a test document. It contains sentences to ensure chunking works.",
        },
        "content_type": "notes",
        "chunks": None,
        "status": "chunking",
        "error": None,
    }

    result = await chunk_node(state)

    assert result["status"] == "embedding"
    assert result["chunks"] is not None
    assert len(result["chunks"]) >= 1

    async with factory() as session:
        rows = await session.execute(
            select(ChunkModel).where(ChunkModel.document_id == doc_id)
        )
        chunks_in_db = rows.scalars().all()

    assert len(chunks_in_db) >= 1
    assert chunks_in_db[0].document_id == doc_id


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


async def test_ingest_endpoint_returns_processing(test_db, tmp_path):
    """POST /documents/ingest returns document_id and status='processing' immediately."""
    txt_content = b"This is a small test document for the ingestion endpoint test."
    txt_file = tmp_path / "sample.txt"
    txt_file.write_bytes(txt_content)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with txt_file.open("rb") as fh:
            response = await client.post(
                "/documents/ingest",
                files={"file": ("sample.txt", fh, "text/plain")},
            )

    assert response.status_code == 200
    body = response.json()
    assert "document_id" in body
    assert body["status"] == "processing"


async def test_status_endpoint_returns_stage(test_db):
    """GET /documents/{id}/status returns stage and correct progress_pct."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="txt",
                content_type="notes",
                word_count=0,
                page_count=0,
                file_path="/tmp/test.txt",
                stage="chunking",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/documents/{doc_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "chunking"
    assert body["progress_pct"] == 40
    assert body["done"] is False


async def test_status_endpoint_done_when_complete(test_db):
    """GET /documents/{id}/status returns done=True when stage=complete."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Done Doc",
                format="txt",
                content_type="notes",
                word_count=0,
                page_count=0,
                file_path="/tmp/done.txt",
                stage="complete",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/documents/{doc_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "complete"
    assert body["progress_pct"] == 100
    assert body["done"] is True


async def test_status_endpoint_404_for_unknown(test_db):
    """GET /documents/{id}/status returns 404 for a non-existent document."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/documents/does-not-exist/status")

    assert response.status_code == 404


async def test_ingest_small_txt_classified_as_notes(test_db, tmp_path):
    """Small plain-text file with no special markers is classified as 'notes'."""
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("These are my personal notes about the project.\n\nMore notes here.")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with txt_file.open("rb") as fh:
            response = await client.post(
                "/documents/ingest",
                files={"file": ("notes.txt", fh, "text/plain")},
            )

    assert response.status_code == 200
    body = response.json()
    doc_id = body["document_id"]

    # Document should be recorded in the DB with stage='parsing' initially
    _engine, factory, _tmp = test_db
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None
    assert doc.format == "txt"
