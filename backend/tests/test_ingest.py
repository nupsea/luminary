import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import ChunkModel, DocumentModel
from app.services.content_classifier import classify_content
from app.workflows.ingestion import IngestionState, chunk_node
from tests.factories import make_document

# Classification heuristic unit tests (pure functions, no DB)


def test_classify_conversation_by_speaker_pattern():
    text = "Alice: Good morning.\nBob: Hello Alice, how are you today?"
    assert classify_content(text, [], 50, "txt") == "conversation"


def test_classify_conversation_by_keyword():
    text = "interviewer: What brings you here?\nguest: I wanted to discuss the topic."
    assert classify_content(text, [], 50, "txt") == "conversation"


def test_classify_paper_by_abstract():
    text = "abstract\n\nThis paper presents a new methodology for testing software."
    assert classify_content(text, [], 500, "txt") == "paper"


def test_classify_book_by_chapters_and_length():
    headings = [
        {"heading": "Chapter 1 Introduction", "level": 1},
        {"heading": "Chapter 2 Background", "level": 1},
    ]
    text = "word " * 41000
    assert classify_content(text, headings, 41000, "txt") == "book"


def test_classify_code_by_extension():
    assert classify_content("def foo(): pass", [], 5, "py") == "code"


def test_classify_defaults_to_notes():
    assert classify_content("some random text about everyday life", [], 100, "txt") == "notes"


# Test DB fixture — isolates each test with an in-memory SQLite database


# Workflow node tests


async def test_chunk_node_writes_to_db(test_db):
    """chunk_node should persist chunks to the chunks table."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                form="entries",
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
        "form": "entries",
        "chunks": None,
        "status": "chunking",
        "error": None,
    }

    result = await chunk_node(state)

    assert result["status"] == "embedding"
    assert result["chunks"] is not None
    assert len(result["chunks"]) >= 1

    async with factory() as session:
        rows = await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id))
        chunks_in_db = rows.scalars().all()

    assert len(chunks_in_db) >= 1
    assert chunks_in_db[0].document_id == doc_id


# HTTP endpoint tests


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
            make_document(
                id=doc_id,
                title="Test",
                form="entries",
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
            make_document(id=doc_id, title="Done Doc", form="entries", file_path="/tmp/done.txt")
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


async def test_classify_node_stores_the_measured_subject(test_db, monkeypatch):
    """The subject is the model's answer; the shape is measured without one."""
    from unittest.mock import AsyncMock, MagicMock

    import litellm

    import app.services.llm as llm_module
    from app.workflows.ingestion import classify_node

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "technical"
    mock_response.usage = None
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(return_value=mock_response))
    llm_module._llm_service = None  # force re-creation against mock

    state: IngestionState = {
        "document_id": "test-llm-ok",
        "file_path": "/tmp/large.txt",
        "format": "txt",
        "parsed_document": {
            "title": "Large Notes",
            "format": "txt",
            "pages": 1,
            "word_count": 6000,
            "sections": [],
            "raw_text": "word " * 6000,
        },
        "chunks": None,
        "status": "classifying",
        "error": None,
    }

    result = await classify_node(state)

    assert result["status"] == "chunking"
    assert result["domain"] == "technical"
    assert result["form"] == "prose"
    assert result["error"] is None


async def test_classify_node_advances_when_the_model_is_down(test_db, monkeypatch):
    """classify_node must not crash when Ollama is unreachable."""
    from unittest.mock import AsyncMock

    import litellm

    import app.services.llm as llm_module
    from app.workflows.ingestion import classify_node

    monkeypatch.setattr(
        litellm,
        "acompletion",
        AsyncMock(side_effect=ConnectionError("Ollama unreachable")),
    )
    llm_module._llm_service = None  # force re-creation against mock

    state: IngestionState = {
        "document_id": "test-llm-down",
        "file_path": "/tmp/large.txt",
        "format": "txt",
        "parsed_document": {
            "title": "Large Generic Document",
            "format": "txt",
            "pages": 1,
            "word_count": 30000,
            "sections": [],
            "raw_text": "Alice: what did you see\nBob: the whole valley\n" * 3000,
        },
        "chunks": None,
        "status": "classifying",
        "error": None,
    }

    result = await classify_node(state)

    # Not raising, and still advancing the pipeline, is the point. The shape is
    # measured without a model; the subject stays unanswered rather than "general".
    assert result["status"] == "chunking"
    assert result["form"] == "dialogue"
    assert result["domain"] is None
    assert result["error"] is None


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


async def test_classify_node_reports_classifying_while_its_probes_wait(test_db, monkeypatch):
    """The domain and register probes queue behind other documents' LLM work, so
    the stage must say what ingestion is waiting on: left at "parsing", an 11 KB
    file reported parsing for three minutes (#142)."""
    from app.workflows.ingestion import classify_node
    from app.workflows.ingestion_nodes import _shared as shared_module
    from app.workflows.ingestion_nodes import parse as parse_module

    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="Chapter",
                form="entries",
                file_path="/tmp/chapter.txt",
                stage="parsing",
            )
        )
        await session.commit()

    seen: list[str] = []

    async def _probe(_text: str) -> None:
        async with factory() as session:
            seen.append((await session.get(DocumentModel, doc_id)).stage)

    monkeypatch.setattr(shared_module, "detect_technical_content", _probe)
    monkeypatch.setattr(parse_module, "detect_register", _probe)

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": "/tmp/chapter.txt",
        "format": "txt",
        "parsed_document": {
            "title": "Chapter",
            "format": "txt",
            "pages": 1,
            "word_count": 12,
            "sections": [],
            "raw_text": "A chapter of prose long enough to be probed for its subject.",
        },
        "form": "entries",
        "chunks": None,
        "status": "classifying",
        "error": None,
    }
    await classify_node(state)
    assert seen and set(seen) == {"classifying"}


async def test_classify_node_asks_the_domain_of_a_reprocessed_document(test_db, monkeypatch):
    """A stored domain does not settle a reprocess: the Federalist Papers stored as a
    technical book stayed technical while the type answered for it (#384)."""
    from app.workflows.ingestion import classify_node
    from app.workflows.ingestion_nodes import _shared as shared_module

    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="Federalist",
                form="reference",
                domain="technical",
                file_path="/tmp/federalist.txt",
                stage="parsing",
            )
        )
        await session.commit()

    async def _general(_text: str) -> bool:
        return False

    monkeypatch.setattr(shared_module, "detect_technical_content", _general)
    state: IngestionState = {
        "document_id": doc_id,
        "file_path": "/tmp/federalist.txt",
        "format": "txt",
        "parsed_document": {
            "title": "Federalist",
            "format": "txt",
            "pages": 1,
            "word_count": 14,
            "sections": [],
            "raw_text": "To the People of the State of New York: the subject speaks for itself.",
        },
        "chunks": None,
        "status": "classifying",
        "error": None,
    }
    result = await classify_node(state)
    assert result["domain"] == "general"
    async with factory() as session:
        assert (await session.get(DocumentModel, doc_id)).domain == "general"
