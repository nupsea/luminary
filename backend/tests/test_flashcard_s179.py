"""S179: Context-aware flashcard generation -- unit tests."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, FlashcardModel
from app.services.flashcard import (
    FlashcardService,
    _classify_chunk,
    _filter_chunks_by_classification,
)

# ---------------------------------------------------------------------------
# Isolated test DB fixture
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


def _make_doc(**kwargs) -> DocumentModel:
    defaults = {
        "id": str(uuid.uuid4()),
        "title": "Designing Data-Intensive Applications",
        "format": "pdf",
        "content_type": "book",
        "word_count": 500,
        "page_count": 10,
        "file_path": "/tmp/ddia.pdf",
        "stage": "complete",
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


def _make_chunk(doc_id: str, text: str, index: int = 0) -> ChunkModel:
    return ChunkModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        section_id=None,
        text=text,
        token_count=len(text.split()),
        page_number=1,
        chunk_index=index,
    )


def _make_flashcard(doc_id: str, question: str, deck: str = "default") -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=str(uuid.uuid4()),
        question=question,
        answer="A distributed system concept.",
        source_excerpt="...",
        deck=deck,
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Test 1: analogy chunk classified and skipped
# ---------------------------------------------------------------------------


def test_analogy_chunk_is_classified_and_skipped():
    """Chunk containing only an analogy is classified as 'analogy' and excluded."""
    analogy_text = (
        "Think of it as a wild boar charging through a forest. "
        "Just as the boar knocks down trees, the process clears the queue. "
        "Imagine a stampede of animals -- similar to the flow of data through the pipeline."
    )
    label = _classify_chunk(analogy_text)
    assert label == "analogy", f"Expected 'analogy', got '{label}'"

    # Standalone analogy chunk (no adjacent concept) must be excluded
    doc_id = str(uuid.uuid4())
    chunk = _make_chunk(doc_id, analogy_text)
    result = _filter_chunks_by_classification([chunk])
    assert result == [], "Standalone analogy chunk must be excluded from eligible set"


# ---------------------------------------------------------------------------
# Test 2: concept chunk produces why/how question with chunk_classification set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concept_chunk_produces_why_how_question(test_db):
    """Concept chunk yields a card with chunk_classification='concept'."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    concept_text = (
        "Therefore, the key idea behind replication is that copies of data are kept "
        "on multiple nodes. As a result, if one node fails, the system can still serve "
        "reads from the remaining replicas. The principle enables fault tolerance."
    )

    async with factory() as session:
        doc = _make_doc(id=doc_id, title="Distributed Systems Engineering")
        # Add 2 chunks so _fetch_chunks(book) skip logic (skips first 1) leaves at least 1
        chunk0 = _make_chunk(doc_id, "Introduction to distributed systems.", index=0)
        chunk1 = _make_chunk(doc_id, concept_text, index=1)
        session.add(doc)
        session.add(chunk0)
        session.add(chunk1)
        await session.commit()

    llm_response = (
        '[{"question": "Why is data replication important in distributed systems?", '
        '"answer": "It enables fault tolerance by keeping copies on multiple nodes.", '
        '"source_excerpt": "copies of data are kept on multiple nodes"}]'
    )

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=llm_response)

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        patch(
            "app.services.flashcard._fetch_existing_embeddings",
            new=AsyncMock(return_value=([], None)),
        ),
    ):
        async with factory() as session:
            cards = await FlashcardService().generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert len(cards) == 1, f"Expected 1 card, got {len(cards)}"
    assert cards[0].chunk_classification == "concept", (
        f"Expected chunk_classification='concept', got '{cards[0].chunk_classification}'"
    )


# ---------------------------------------------------------------------------
# Test 3: near-duplicate card skipped by embedding dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_near_duplicate_skipped_by_embedding_dedup(test_db):
    """Near-duplicate card (cosine >= 0.85) is silently skipped and not inserted."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    concept_text = (
        "Therefore, the key idea behind replication is that copies of data are kept "
        "on multiple nodes. This means the system can still serve reads from remaining replicas."
    )

    async with factory() as session:
        doc = _make_doc(id=doc_id)
        chunk = _make_chunk(doc_id, concept_text)
        existing_card = _make_flashcard(
            doc_id, "Why is replication important in distributed systems?"
        )
        session.add(doc)
        session.add(chunk)
        session.add(existing_card)
        await session.commit()

    llm_response = (
        '[{"question": "Why is replication important in distributed systems?", '
        '"answer": "It keeps copies of data on multiple nodes.", '
        '"source_excerpt": "copies of data are kept on multiple nodes"}]'
    )

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=llm_response)

    # Return identical vectors so cosine = 1.0 (above 0.85 threshold)
    identical_vector = [1.0] + [0.0] * 383
    mock_embedder = MagicMock()
    mock_embedder.encode = MagicMock(
        return_value=[identical_vector, identical_vector]  # candidate + existing
    )

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        # get_embedding_service is lazily imported inside _dedup_check -- patch at source module
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
        # asyncio.to_thread wraps embedder.encode; return pre-canned vectors directly
        patch(
            "asyncio.to_thread",
            new=AsyncMock(return_value=[identical_vector, identical_vector]),
        ),
    ):
        async with factory() as session:
            cards = await FlashcardService().generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert cards == [], f"Expected 0 cards (near-duplicate skipped), got {len(cards)}"
