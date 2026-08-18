"""Unit tests for FlashcardAuditService (S153)."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from stubs import MockLLMService

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel
from app.services.flashcard_audit import FlashcardAuditService

# Isolated test DB fixture (mirrors test_flashcards.py pattern)


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


# Helpers


def _make_doc(doc_id: str | None = None, **kwargs) -> DocumentModel:
    defaults = {
        "id": doc_id or str(uuid.uuid4()),
        "title": "Audit Test Doc",
        "format": "txt",
        "content_type": "notes",
        "word_count": 100,
        "page_count": 1,
        "file_path": "/tmp/test.txt",
        "stage": "complete",
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


def _make_section(
    section_id: str | None = None,
    doc_id: str = "doc-1",
    heading: str = "Chapter 1",
) -> SectionModel:
    return SectionModel(
        id=section_id or str(uuid.uuid4()),
        document_id=doc_id,
        heading=heading,
        level=1,
        page_start=1,
        page_end=2,
        section_order=1,
    )


def _make_chunk(
    chunk_id: str | None = None,
    doc_id: str = "doc-1",
    section_id: str | None = None,
) -> ChunkModel:
    return ChunkModel(
        id=chunk_id or str(uuid.uuid4()),
        document_id=doc_id,
        section_id=section_id,
        text="Sample chunk text for Bloom's audit tests.",
        token_count=10,
        page_number=1,
        chunk_index=0,
    )


def _make_card(
    card_id: str | None = None,
    doc_id: str = "doc-1",
    chunk_id: str | None = None,
    bloom_level: int | None = None,
) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=card_id or str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
        bloom_level=bloom_level,
    )


# Tests


async def test_bloom_gap_for_recall_only_deck(test_db):
    """Deck with only bloom_level=1 cards -> gap entry with missing_bloom_levels=[2,3,4,5,6]."""
    _, factory, _ = test_db
    doc_id = "doc-audit-1"
    section_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        section = _make_section(section_id=section_id, doc_id=doc_id, heading="Section A")
        session.add(section)
        chunk = _make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=section_id)
        session.add(chunk)
        # 5 recall-level cards all bloom_level=1
        for _ in range(5):
            session.add(_make_card(doc_id=doc_id, chunk_id=chunk_id, bloom_level=1))
        await session.commit()

    async with factory() as session:
        service = FlashcardAuditService()
        report = await service.analyze_coverage(doc_id, session)

    assert report["total_cards"] == 5
    assert report["coverage_score"] == 0.0
    assert len(report["gaps"]) == 1
    gap = report["gaps"][0]
    assert gap["section_id"] == section_id
    assert gap["missing_bloom_levels"] == [2, 3, 4, 5, 6]


async def test_coverage_score_zero_with_no_l3_cards(test_db):
    """coverage_score == 0.0 when no section has a card at bloom_level >= 3."""
    _, factory, _ = test_db
    doc_id = "doc-audit-2"
    section_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id))
        session.add(_make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=section_id))
        # Only L1 and L2 cards -- no L3+
        for level in (1, 1, 2):
            session.add(_make_card(doc_id=doc_id, chunk_id=chunk_id, bloom_level=level))
        await session.commit()

    async with factory() as session:
        service = FlashcardAuditService()
        report = await service.analyze_coverage(doc_id, session)

    assert report["coverage_score"] == 0.0


async def test_fill_gaps_creates_l3_plus_cards(test_db):
    """fill_gaps with 2 gap entries creates >= 2 new FlashcardModel rows with bloom_level >= 3."""
    _, factory, _ = test_db
    doc_id = "doc-audit-3"
    section_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id, heading="Test Section"))
        session.add(_make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=section_id))
        await session.commit()

    # LLM returns one card at the target bloom level. The excerpt quotes the seeded
    # chunk: gap-fill cards go through the same grounding gate as every other path,
    # so a stub that invents a quote is testing the gate, not the audit.
    llm_response = json.dumps(
        [
            {
                "question": "How would you apply X in production?",
                "answer": "Use X by following steps A, B, C.",
                "source_excerpt": "Sample chunk text for Bloom's audit tests.",
                # The type fixes the level now (I-28: the prompt names none), and
                # `concept_explanation` is a level-2 shape. This stub used to
                # claim level 3 while naming a level-2 type; the code resolves
                # that in favour of the type, so the fixture states a type whose
                # level is what the gap being filled asked for.
                "flashcard_type": "trace",
            }
        ]
    )
    mock_llm = MockLLMService(response=llm_response)

    gaps = [
        {
            "section_id": section_id,
            "section_heading": "Test Section",
            "missing_bloom_levels": [3, 4],
        }
    ]

    with patch("app.services.flashcard_audit.get_llm_service", return_value=mock_llm):
        async with factory() as session:
            service = FlashcardAuditService()
            created = await service.fill_gaps(doc_id, gaps, session)

    # 2 levels requested (3 and 4), each generates 1 card -> created >= 2
    assert created >= 2

    async with factory() as session:
        from sqlalchemy import select as sa_select
        from sqlalchemy import text as sa_text

        result = await session.execute(
            sa_select(FlashcardModel)
            .where(FlashcardModel.document_id == doc_id)
            .where(FlashcardModel.bloom_level >= 3)
        )
        high_bloom_cards = result.scalars().all()
        # A card that never enters the FTS index exists and cannot be found: this
        # path inserted without indexing, so every gap-fill card was unsearchable.
        indexed = await session.execute(
            sa_text("SELECT COUNT(*) FROM flashcards_fts_content WHERE c2 = :fid"),
            {"fid": high_bloom_cards[0].id},
        )
        assert indexed.scalar_one() == 1, "a gap-fill card must be searchable"
    assert len(high_bloom_cards) >= 2


@pytest.mark.asyncio
async def test_gap_fill_shows_the_model_the_section_text(test_db):
    """A card cannot be written from a heading.

    This path used to prompt with the section *heading* and nothing else, while the
    system prompt asked for a `source_excerpt` -- so every quote it produced was
    necessarily invented, and the card entered the deck under a "Source" blockquote
    with no way to tell. The passage has to be in the prompt, and the quote has to
    be in the passage.
    """
    _, factory, _ = test_db
    doc_id = "doc-audit-4"
    section_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id, heading="Test Section"))
        session.add(_make_chunk(chunk_id=str(uuid.uuid4()), doc_id=doc_id, section_id=section_id))
        await session.commit()

    invented = json.dumps(
        [
            {
                "question": "How would you apply X in production?",
                "answer": "Use X by following steps A, B, C.",
                "source_excerpt": "a sentence that appears nowhere in the section",
                "flashcard_type": "concept_explanation",
                "bloom_level": 3,
            }
        ]
    )
    mock_llm = MockLLMService(response=invented)
    gaps = [
        {
            "section_id": section_id,
            "section_heading": "Test Section",
            "missing_bloom_levels": [3],
        }
    ]
    with patch("app.services.flashcard_audit.get_llm_service", return_value=mock_llm):
        async with factory() as session:
            created = await FlashcardAuditService().fill_gaps(doc_id, gaps, session)

    assert created == 0, "a gap-fill card whose quote is not in the section must not be kept"
    assert "Sample chunk text for Bloom's audit tests." in mock_llm.last_prompt, (
        "the section text must reach the model -- otherwise it is asked to quote "
        "a passage it has never seen"
    )
