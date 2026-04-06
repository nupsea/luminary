"""Tests for S188: context-rich flashcard generation with source grounding."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel
from app.services.flashcard import (
    FlashcardService,
    _build_enriched_text,
    _get_section_context_for_chunks,
    _resolve_section_heading,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOC_ID = "doc-s188"
SEC_ID = "sec-chapter12"
PARENT_SEC_ID = "sec-book12"


def _make_doc(content_type: str = "book") -> DocumentModel:
    return DocumentModel(
        id=DOC_ID,
        title="The Odyssey",
        format="txt",
        content_type=content_type,
        word_count=50000,
        page_count=200,
        file_path="/tmp/odyssey.txt",
        stage="complete",
    )


def _make_parent_section() -> SectionModel:
    return SectionModel(
        id=PARENT_SEC_ID,
        document_id=DOC_ID,
        heading="Book XII",
        level=1,
        section_order=12,
        preview="The Sirens, Scylla and Charybdis",
    )


def _make_section() -> SectionModel:
    return SectionModel(
        id=SEC_ID,
        document_id=DOC_ID,
        heading="The Sirens",
        level=2,
        section_order=13,
        preview="Ulysses and the Sirens",
        parent_section_id=PARENT_SEC_ID,
    )


def _make_chunks(n: int = 3) -> list[ChunkModel]:
    chunks = []
    for i in range(n):
        chunks.append(
            ChunkModel(
                id=f"chunk-{i}",
                document_id=DOC_ID,
                section_id=SEC_ID,
                text=(
                    f"Chunk {i}: Ulysses ordered his men to plug their ears with wax "
                    "while he himself was tied to the mast. The Sirens sang but could not "
                    "lure the crew. This was a test of Ulysses' wisdom and self-control."
                ),
                token_count=40,
                page_number=i + 1,
                chunk_index=i,
            )
        )
    return chunks


def _make_bloom_l3_response(count: int = 5) -> str:
    """Create an LLM response with >= 50% Bloom L3+ cards."""
    cards = []
    for i in range(count):
        bloom = 3 + (i % 4)  # cycles through 3, 4, 5, 6
        cards.append({
            "question": f"Why does Ulysses choose to resist the Sirens in Book XII (card {i})?",
            "answer": f"In Book XII - The Sirens, Ulysses demonstrates wisdom by... (card {i})",
            "source_excerpt": f"Ulysses ordered his men... (excerpt {i})",
            "bloom_level": bloom,
        })
    return json.dumps(cards)


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_section_context_for_chunks(test_db):
    """Section context map includes heading and parent heading."""
    _engine, factory, _tmp = test_db
    async with factory() as session:
        session.add(_make_parent_section())
        session.add(_make_section())
        await session.commit()

        chunks = _make_chunks(2)
        ctx = await _get_section_context_for_chunks(chunks, session)

        assert SEC_ID in ctx
        heading, parent_heading = ctx[SEC_ID]
        assert heading == "The Sirens"
        assert parent_heading == "Book XII"


def test_build_enriched_text_includes_heading():
    """Enriched text includes [parent > heading] prefix."""
    chunks = _make_chunks(1)
    section_ctx = {SEC_ID: ("The Sirens", "Book XII")}
    text, first_id = _build_enriched_text(chunks, section_ctx)

    assert "[Book XII > The Sirens]" in text
    assert first_id == "chunk-0"


def test_resolve_section_heading_with_parent():
    """Section heading resolves to 'Parent - Child' format."""
    chunk = _make_chunks(1)[0]
    section_ctx = {SEC_ID: ("The Sirens", "Book XII")}
    result = _resolve_section_heading(chunk, section_ctx)
    assert result == "Book XII - The Sirens"


def test_resolve_section_heading_no_parent():
    """Section heading without parent returns just the heading."""
    chunk = _make_chunks(1)[0]
    section_ctx = {SEC_ID: ("The Sirens", None)}
    result = _resolve_section_heading(chunk, section_ctx)
    assert result == "The Sirens"


def test_resolve_section_heading_no_section():
    """Chunk with no section_id returns None."""
    chunk = ChunkModel(
        id="chunk-no-sec",
        document_id=DOC_ID,
        section_id=None,
        text="No section chunk",
        token_count=5,
        page_number=1,
        chunk_index=0,
    )
    result = _resolve_section_heading(chunk, {})
    assert result is None


# ---------------------------------------------------------------------------
# Tests: generate() produces bloom_level and section_heading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_book_produces_bloom_l3_cards(test_db):
    """generate() for a book document produces cards with >= 50% bloom_level >= 3."""
    _engine, factory, _tmp = test_db

    async with factory() as session:
        doc = _make_doc(content_type="book")
        session.add(doc)
        session.add(_make_parent_section())
        session.add(_make_section())
        for c in _make_chunks(3):
            session.add(c)
        await session.commit()

    # Mock LLM to return bloom_level in response
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=_make_bloom_l3_response(6))

    # Mock embedder to skip dedup
    mock_embedder = AsyncMock()
    mock_embedder.encode = lambda texts: [[0.0] * 1024 for _ in texts]

    # Mock entity lookup (non-fatal, returns names)
    mock_graph_svc = AsyncMock()
    mock_graph_svc.get_entities_by_type_for_document = lambda _: {
        "PERSON": ["Ulysses", "Circe"],
        "PLACE": ["Ithaca", "Troy"],
    }

    svc = FlashcardService()

    async with factory() as session:
        with (
            patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
            patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
            patch("app.services.graph.get_graph_service", return_value=mock_graph_svc),
        ):
            cards = await svc.generate(
                document_id=DOC_ID,
                scope="full",
                section_heading=None,
                count=6,
                session=session,
                difficulty="medium",
            )

    assert len(cards) >= 1
    bloom_l3_plus = [c for c in cards if c.bloom_level is not None and c.bloom_level >= 3]
    assert len(bloom_l3_plus) >= len(cards) * 0.5, (
        f"Expected >= 50% Bloom L3+, got {len(bloom_l3_plus)}/{len(cards)}"
    )


@pytest.mark.asyncio
async def test_generate_populates_section_heading(test_db):
    """generate() populates section_heading from chunk -> section join."""
    _engine, factory, _tmp = test_db

    async with factory() as session:
        doc = _make_doc(content_type="book")
        session.add(doc)
        session.add(_make_parent_section())
        session.add(_make_section())
        for c in _make_chunks(3):
            session.add(c)
        await session.commit()

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=_make_bloom_l3_response(3))

    mock_embedder = AsyncMock()
    mock_embedder.encode = lambda texts: [[0.0] * 1024 for _ in texts]

    mock_graph_svc = AsyncMock()
    mock_graph_svc.get_entities_by_type_for_document = lambda _: {}

    svc = FlashcardService()

    async with factory() as session:
        with (
            patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
            patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
            patch("app.services.graph.get_graph_service", return_value=mock_graph_svc),
        ):
            cards = await svc.generate(
                document_id=DOC_ID,
                scope="full",
                section_heading=None,
                count=3,
                session=session,
                difficulty="medium",
            )

    assert len(cards) >= 1
    # All cards should have section_heading populated from the section context
    for card in cards:
        assert card.section_heading is not None, "section_heading should be populated"
        assert "Book XII" in card.section_heading
        assert "The Sirens" in card.section_heading


@pytest.mark.asyncio
async def test_flashcard_response_includes_section_heading(test_db):
    """FlashcardResponse schema includes section_heading field."""
    from app.routers.flashcards import FlashcardResponse

    now = datetime.now(UTC)
    card = FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=DOC_ID,
        chunk_id="chunk-0",
        source="document",
        question="Why does Ulysses resist the Sirens?",
        answer="In Book XII, Ulysses...",
        source_excerpt="Ulysses ordered his men...",
        difficulty="medium",
        is_user_edited=False,
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
        section_heading="Book XII - The Sirens",
        bloom_level=4,
    )
    resp = FlashcardResponse.model_validate(card, from_attributes=True)
    assert resp.section_heading == "Book XII - The Sirens"
    assert resp.bloom_level == 4
