"""Tests for GET /sections/{document_id} endpoint and conversation metadata (S60).

(a) test_sections_endpoint_returns_ordered_list
(b) test_sections_endpoint_chunk_count_matches_db
(c) test_conversation_metadata_endpoint_returns_roster
"""

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
from app.workflows.ingestion import IngestionState, _chunk_book, _chunk_conversation

# ---------------------------------------------------------------------------
# Shared fixture
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


def _make_doc(doc_id: str, content_type: str = "book") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="Test Doc",
        format="txt",
        content_type=content_type,
        word_count=300,
        page_count=3,
        file_path="/tmp/test.txt",
        stage="chunking",
        tags=[],
    )


def _make_book_state(doc_id: str) -> IngestionState:
    sections = [
        {
            "heading": f"Chapter {i + 1}",
            "level": 1,
            "text": f"Chapter {i + 1} content. " * 40,
            "page_start": i,
            "page_end": i,
        }
        for i in range(3)
    ]
    return IngestionState(
        document_id=doc_id,
        file_path="/tmp/test.txt",
        format="txt",
        parsed_document={
            "title": "Test Book",
            "format": "txt",
            "pages": 3,
            "word_count": 300,
            "sections": sections,
            "raw_text": " ".join(s["text"] for s in sections),
        },
        content_type="book",
        chunks=None,
        status="chunking",
        error=None,
    )


PLAIN_CONV = "\n".join(
    [
        "Alice: Good morning everyone!",
        "Bob: Morning! Ready to begin?",
        "Alice: Yes, let's start.",
        "Carol: Joining now.",
        "Bob: Great, let's go.",
        "Alice: Today's agenda is clear.",
        "Carol: Agreed.",
        "Bob: Sounds good.",
        "Alice: Any questions?",
        "Carol: None from me.",
    ]
)


def _make_conv_state(doc_id: str) -> IngestionState:
    return IngestionState(
        document_id=doc_id,
        file_path="/tmp/conv.txt",
        format="txt",
        parsed_document={
            "title": "Test Conversation",
            "format": "txt",
            "pages": 0,
            "word_count": len(PLAIN_CONV.split()),
            "sections": [],
            "raw_text": PLAIN_CONV,
        },
        content_type="conversation",
        chunks=None,
        status="chunking",
        error=None,
    )


# ---------------------------------------------------------------------------
# (a) test_sections_endpoint_returns_ordered_list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sections_endpoint_returns_ordered_list(test_db):
    """GET /sections/{id} returns sections ordered by section_order."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, "book"))
        await session.commit()

    state = _make_book_state(doc_id)
    await _chunk_book(state, state["parsed_document"], doc_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/sections/{doc_id}")

    assert resp.status_code == 200
    sections = resp.json()
    assert len(sections) == 3, f"Expected 3 sections, got {len(sections)}"

    orders = [s["section_order"] for s in sections]
    assert orders == sorted(orders), "Sections must be ordered by section_order"
    assert sections[0]["heading"] == "Chapter 1"
    assert sections[1]["heading"] == "Chapter 2"
    assert sections[2]["heading"] == "Chapter 3"


# ---------------------------------------------------------------------------
# (b) test_sections_endpoint_chunk_count_matches_db
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sections_endpoint_chunk_count_matches_db(test_db):
    """chunk_count in /sections response matches actual chunks in DB."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, "book"))
        await session.commit()

    state = _make_book_state(doc_id)
    await _chunk_book(state, state["parsed_document"], doc_id)

    # Collect actual chunk counts from DB
    async with factory() as session:
        from app.models import SectionModel

        sections_result = await session.execute(
            select(SectionModel).where(SectionModel.document_id == doc_id)
        )
        db_sections = sections_result.scalars().all()
        db_counts = {}
        for s in db_sections:
            chunks_result = await session.execute(
                select(ChunkModel).where(ChunkModel.section_id == s.id)
            )
            db_counts[s.id] = len(chunks_result.scalars().all())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/sections/{doc_id}")

    assert resp.status_code == 200
    api_sections = resp.json()

    for api_sec in api_sections:
        sid = api_sec["id"]
        expected = db_counts.get(sid, 0)
        assert api_sec["chunk_count"] == expected, (
            f"Section {api_sec['heading']}: API chunk_count={api_sec['chunk_count']}, "
            f"DB count={expected}"
        )
        assert api_sec["chunk_count"] > 0, (
            f"Section '{api_sec['heading']}' should have at least one chunk"
        )


# ---------------------------------------------------------------------------
# (c) test_conversation_metadata_endpoint_returns_roster
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_conversation_metadata_endpoint_returns_roster(test_db):
    """GET /documents/{id}/conversation returns speaker roster and timeline."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    conv_doc = DocumentModel(
        id=doc_id,
        title="Test Conversation",
        format="txt",
        content_type="conversation",
        word_count=100,
        page_count=0,
        file_path="/tmp/conv.txt",
        stage="chunking",
        tags=[],
    )
    async with factory() as session:
        session.add(conv_doc)
        await session.commit()

    state = _make_conv_state(doc_id)
    await _chunk_conversation(state, state["parsed_document"], doc_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/documents/{doc_id}/conversation")

    assert resp.status_code == 200
    data = resp.json()
    assert "speakers" in data
    assert "total_turns" in data
    assert "has_timestamps" in data
    assert len(data["speakers"]) > 0, "Should detect at least one speaker"

    # Wrong content type → 400
    book_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=book_id,
                title="A Book",
                format="txt",
                content_type="book",
                word_count=1000,
                page_count=0,
                file_path="/tmp/book.txt",
                stage="complete",
                tags=[],
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        bad_resp = await client.get(f"/documents/{book_id}/conversation")

    assert bad_resp.status_code == 400
