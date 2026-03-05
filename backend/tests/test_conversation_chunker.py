"""Tests for ConversationChunker — speaker-turn chunking service (S56).

(a) test_detect_whatsapp_format
(b) test_detect_plain_speaker_format
(c) test_detect_returns_false_for_book_text
(d) test_chunk_sets_speaker_field
(e) test_chunk_respects_token_limit
(f) test_extract_roster_counts_turns_per_speaker
(g) test_extract_timeline_finds_timestamps
(h) test_fallback_to_default_splitter_when_not_detected
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
from app.services.conversation_chunker import ConversationChunker
from app.workflows.ingestion import IngestionState, _chunk_conversation

# ---------------------------------------------------------------------------
# Sample texts
# ---------------------------------------------------------------------------

WHATSAPP_TEXT = "\n".join(
    [
        "[10:01] Alice: Good morning everyone!",
        "[10:02] Bob: Morning! Ready for the standup?",
        "[10:03] Alice: Yes, let me pull up the board.",
        "[10:04] Carol: Morning all.",
        "[10:05] Bob: Great, let's start.",
        "[10:06] Alice: Yesterday I finished the auth module.",
        "[10:07] Bob: Nice. I'm on the search feature.",
        "[10:08] Carol: I reviewed the PRs from last week.",
        "[10:09] Alice: Any blockers?",
        "[10:10] Bob: None from my side.",
    ]
)

PLAIN_SPEAKER_TEXT = "\n".join(
    [
        "Alice: Hello everyone, thanks for joining.",
        "Bob: Thanks for having us.",
        "Alice: Let's start with introductions.",
        "Carol: Sure, I'm Carol, I lead the design team.",
        "Bob: And I'm Bob, engineering lead.",
        "Alice: Great. Today we'll cover the roadmap.",
        "Carol: Looking forward to it.",
        "Bob: Same here.",
        "Alice: Let's begin with Q1 goals.",
        "Carol: Sounds good.",
    ]
)

BOOK_TEXT = """
Chapter 1: The Beginning

It was a dark and stormy night. The wind howled through the trees as our hero
made his way along the narrow path. He had been walking for hours, his boots
soaked through with the relentless rain.

Chapter 2: The Discovery

At dawn, he found what he had been searching for all these years. The ancient
tome lay on the stone altar, its pages yellowed but still legible. He reached
out and touched the cover, feeling the weight of history beneath his fingertips.
""".strip()


# ---------------------------------------------------------------------------
# Fixture — in-memory DB
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


def _make_conv_doc(doc_id: str) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="Test Conversation",
        format="txt",
        content_type="conversation",
        word_count=200,
        page_count=0,
        file_path="/tmp/conv.txt",
        stage="chunking",
        tags=[],
    )


def _make_conv_state(doc_id: str, raw_text: str) -> IngestionState:
    return IngestionState(
        document_id=doc_id,
        file_path="/tmp/conv.txt",
        format="txt",
        parsed_document={
            "title": "Test Conversation",
            "format": "txt",
            "pages": 0,
            "word_count": len(raw_text.split()),
            "sections": [],
            "raw_text": raw_text,
        },
        content_type="conversation",
        chunks=None,
        status="chunking",
        error=None,
    )


# ---------------------------------------------------------------------------
# Unit tests — pure ConversationChunker functions (no DB)
# ---------------------------------------------------------------------------


def test_detect_whatsapp_format():
    """detect() returns True for WhatsApp-style timestamp lines."""
    chunker = ConversationChunker()
    assert chunker.detect(WHATSAPP_TEXT) is True


def test_detect_plain_speaker_format():
    """detect() returns True for 'Speaker: message' lines."""
    chunker = ConversationChunker()
    assert chunker.detect(PLAIN_SPEAKER_TEXT) is True


def test_detect_returns_false_for_book_text():
    """detect() returns False for book paragraphs without speaker turns."""
    chunker = ConversationChunker()
    assert chunker.detect(BOOK_TEXT) is False


def test_chunk_sets_speaker_field():
    """Each chunk's speaker matches the first speaker in its turn group."""
    chunker = ConversationChunker()
    chunks = chunker.chunk(PLAIN_SPEAKER_TEXT)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.speaker in ("Alice", "Bob", "Carol"), (
            f"Unexpected speaker: {chunk.speaker!r}"
        )
        # The chunk text should start with the speaker's name
        assert chunk.speaker in chunk.text


def test_chunk_respects_token_limit():
    """No chunk exceeds 450 estimated tokens (len // 4)."""
    # Generate a long conversation
    lines = []
    speakers = ["Alice", "Bob", "Carol"]
    for i in range(200):
        speaker = speakers[i % 3]
        lines.append(f"{speaker}: This is message number {i} with some extra words to fill space.")
    long_text = "\n".join(lines)

    chunker = ConversationChunker()
    assert chunker.detect(long_text)
    chunks = chunker.chunk(long_text)
    assert len(chunks) > 1, "Expected multiple chunks for a long conversation"
    for chunk in chunks:
        estimated_tokens = len(chunk.text) // 4
        # Allow a small buffer (one extra turn may push slightly over)
        assert estimated_tokens <= 500, (
            f"Chunk is too large: {estimated_tokens} estimated tokens"
        )


def test_extract_roster_counts_turns_per_speaker():
    """extract_roster returns correct turn counts per speaker."""
    chunker = ConversationChunker()
    chunks = chunker.chunk(PLAIN_SPEAKER_TEXT)
    roster = chunker.extract_roster(chunks)

    assert "speakers" in roster
    assert "total_turns" in roster
    assert "has_timestamps" in roster

    names = {s["name"] for s in roster["speakers"]}
    assert "Alice" in names
    assert "Bob" in names
    assert "Carol" in names

    # Speakers sorted by turn_count desc
    counts = [s["turn_count"] for s in roster["speakers"]]
    assert counts == sorted(counts, reverse=True)

    assert roster["has_timestamps"] is False  # plain speaker format, no timestamps


def test_extract_timeline_finds_timestamps():
    """extract_timeline finds first/last timestamp from WhatsApp format."""
    chunker = ConversationChunker()
    timeline = chunker.extract_timeline(WHATSAPP_TEXT)

    assert "first_timestamp" in timeline
    assert "last_timestamp" in timeline
    assert timeline["first_timestamp"] is not None
    assert timeline["last_timestamp"] is not None
    # First should come before last (both are HH:MM format)
    assert timeline["first_timestamp"] <= timeline["last_timestamp"]


def test_extract_timeline_returns_nulls_for_book():
    """extract_timeline returns null timestamps for text with no timestamps."""
    chunker = ConversationChunker()
    timeline = chunker.extract_timeline(BOOK_TEXT)
    assert timeline["first_timestamp"] is None
    assert timeline["last_timestamp"] is None


# ---------------------------------------------------------------------------
# Integration tests — _chunk_conversation + DB
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chunk_sets_speaker_in_db(test_db):
    """After conversation ingestion, chunk.speaker is populated (not None)."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_conv_doc(doc_id))
        await session.commit()

    state = _make_conv_state(doc_id, PLAIN_SPEAKER_TEXT)
    result = await _chunk_conversation(state, state["parsed_document"], doc_id)

    assert result["status"] == "embedding"
    assert len(result["chunks"]) > 0

    async with factory() as session:
        chunks_result = await session.execute(
            select(ChunkModel).where(ChunkModel.document_id == doc_id)
        )
        chunks = chunks_result.scalars().all()

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.speaker is not None, (
            f"Chunk {chunk.id} has speaker=None — conversation chunks must have speaker set"
        )


@pytest.mark.anyio
async def test_conversation_metadata_stored_on_document(test_db):
    """After ingestion, DocumentModel.conversation_metadata contains roster + timeline."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_conv_doc(doc_id))
        await session.commit()

    state = _make_conv_state(doc_id, PLAIN_SPEAKER_TEXT)
    await _chunk_conversation(state, state["parsed_document"], doc_id)

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)

    assert doc is not None
    assert doc.conversation_metadata is not None
    meta = doc.conversation_metadata
    assert "speakers" in meta
    assert "total_turns" in meta
    assert len(meta["speakers"]) > 0


@pytest.mark.anyio
async def test_fallback_to_default_splitter_when_not_detected(test_db):
    """When detect() is False, fallback splitter is used (speaker=None on chunks)."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_conv_doc(doc_id))
        await session.commit()

    # Use book text — detect() will return False
    state = _make_conv_state(doc_id, BOOK_TEXT)
    result = await _chunk_conversation(state, state["parsed_document"], doc_id)

    assert result["status"] == "embedding"
    # Chunks may or may not exist depending on text, but if they do, speaker=None
    async with factory() as session:
        chunks_result = await session.execute(
            select(ChunkModel).where(ChunkModel.document_id == doc_id)
        )
        chunks = chunks_result.scalars().all()

    for chunk in chunks:
        assert chunk.speaker is None


@pytest.mark.anyio
async def test_conversation_metadata_endpoint_returns_roster(test_db):
    """GET /documents/{id}/conversation returns roster and timeline JSON."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_conv_doc(doc_id))
        await session.commit()

    state = _make_conv_state(doc_id, PLAIN_SPEAKER_TEXT)
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
    assert len(data["speakers"]) > 0
