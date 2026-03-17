"""Unit tests for DeckHealthService (S160)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel
from app.services.deck_health import DeckHealthService

# ---------------------------------------------------------------------------
# Isolated test DB fixture (mirrors test_flashcard_audit.py pattern)
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


def _make_doc(doc_id: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Health Test Doc",
        format="txt",
        content_type="notes",
        word_count=100,
        page_count=1,
        file_path="/tmp/test.txt",
        stage="complete",
    )


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
        text="Sample chunk text for deck health tests.",
        token_count=10,
        page_number=1,
        chunk_index=0,
    )


def _make_card(
    card_id: str | None = None,
    doc_id: str = "doc-1",
    chunk_id: str | None = None,
    fsrs_stability: float = 0.0,
    fsrs_state: str = "new",
    last_review: datetime | None = None,
) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=card_id or str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
        fsrs_state=fsrs_state,
        fsrs_stability=fsrs_stability,
        fsrs_difficulty=0.0,
        due_date=now,
        reps=0,
        lapses=0,
        last_review=last_review,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_analyze_orphaned_cards(test_db):
    """Card whose chunk points to a section_id not in SectionModel is counted as orphaned."""
    _, factory, _ = test_db
    doc_id = "doc-health-1"
    valid_section_id = str(uuid.uuid4())
    orphan_section_id = str(uuid.uuid4())  # NOT added to SectionModel
    chunk_id = str(uuid.uuid4())
    orphan_chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=valid_section_id, doc_id=doc_id))
        session.add(_make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=valid_section_id))
        # Chunk pointing to a section that was deleted
        session.add(
            _make_chunk(chunk_id=orphan_chunk_id, doc_id=doc_id, section_id=orphan_section_id)
        )
        orphan_card = _make_card(doc_id=doc_id, chunk_id=orphan_chunk_id)
        valid_card = _make_card(doc_id=doc_id, chunk_id=chunk_id)
        session.add(orphan_card)
        session.add(valid_card)
        await session.commit()

    async with factory() as session:
        svc = DeckHealthService()
        report = await svc.analyze(doc_id, session)

    assert report["orphaned"] == 1
    assert orphan_card.id in report["orphaned_ids"]
    assert valid_card.id not in report["orphaned_ids"]


async def test_analyze_mastered_cards(test_db):
    """Cards with fsrs_stability > 180 are counted as mastered."""
    _, factory, _ = test_db
    doc_id = "doc-health-2"
    chunk_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id))
        session.add(_make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=section_id))
        # Two mastered cards (stability > 180)
        session.add(_make_card(doc_id=doc_id, chunk_id=chunk_id, fsrs_stability=200.0))
        session.add(_make_card(doc_id=doc_id, chunk_id=chunk_id, fsrs_stability=250.0))
        # One non-mastered card
        session.add(_make_card(doc_id=doc_id, chunk_id=chunk_id, fsrs_stability=5.0))
        await session.commit()

    async with factory() as session:
        svc = DeckHealthService()
        report = await svc.analyze(doc_id, session)

    assert report["mastered"] == 2


async def test_analyze_stale_cards(test_db):
    """Card with last_review > 90 days ago and stability < 7 is counted as stale."""
    _, factory, _ = test_db
    doc_id = "doc-health-3"
    chunk_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    old_review = datetime.now(UTC) - timedelta(days=91)

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id))
        session.add(_make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=section_id))
        # Stale: last_review 91 days ago, stability 5 (< 7)
        stale_card = _make_card(
            doc_id=doc_id,
            chunk_id=chunk_id,
            fsrs_stability=5.0,
            last_review=old_review,
        )
        # Not stale: recently reviewed
        fresh_card = _make_card(
            doc_id=doc_id,
            chunk_id=chunk_id,
            fsrs_stability=5.0,
            last_review=datetime.now(UTC) - timedelta(days=10),
        )
        session.add(stale_card)
        session.add(fresh_card)
        await session.commit()

    async with factory() as session:
        svc = DeckHealthService()
        report = await svc.analyze(doc_id, session)

    assert report["stale"] == 1
    assert stale_card.id in report["stale_ids"]
    assert fresh_card.id not in report["stale_ids"]


async def test_analyze_uncovered_sections(test_db):
    """SectionModel rows with no linked flashcards are counted as uncovered."""
    _, factory, _ = test_db
    doc_id = "doc-health-4"
    section_a_id = str(uuid.uuid4())
    section_b_id = str(uuid.uuid4())  # uncovered: no cards
    chunk_a_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_a_id, doc_id=doc_id, heading="Section A"))
        session.add(_make_section(section_id=section_b_id, doc_id=doc_id, heading="Section B"))
        session.add(_make_chunk(chunk_id=chunk_a_id, doc_id=doc_id, section_id=section_a_id))
        # Only section A has a card
        session.add(_make_card(doc_id=doc_id, chunk_id=chunk_a_id))
        await session.commit()

    async with factory() as session:
        svc = DeckHealthService()
        report = await svc.analyze(doc_id, session)

    assert report["uncovered_sections"] == 1
    assert section_b_id in report["uncovered_section_ids"]
    assert section_a_id not in report["uncovered_section_ids"]


async def test_archive_mastered_sets_state(test_db):
    """archive_mastered sets fsrs_state='archived' for mastered cards; returns correct count."""
    _, factory, _ = test_db
    doc_id = "doc-health-5"
    chunk_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id))
        session.add(_make_chunk(chunk_id=chunk_id, doc_id=doc_id, section_id=section_id))
        # 3 mastered cards
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for cid in ids:
            session.add(
                _make_card(card_id=cid, doc_id=doc_id, chunk_id=chunk_id, fsrs_stability=200.0)
            )
        # 1 non-mastered card
        session.add(_make_card(doc_id=doc_id, chunk_id=chunk_id, fsrs_stability=5.0))
        await session.commit()

    async with factory() as session:
        svc = DeckHealthService()
        count = await svc.archive_mastered(doc_id, session)

    assert count == 3

    # Verify cards are archived in DB, not deleted
    from sqlalchemy import select as sa_select

    async with factory() as session:
        result = await session.execute(
            sa_select(FlashcardModel)
            .where(FlashcardModel.document_id == doc_id)
            .where(FlashcardModel.fsrs_state == "archived")
        )
        archived = result.scalars().all()
    assert len(archived) == 3

    # Total cards still 4 (none deleted)
    async with factory() as session:
        result = await session.execute(
            sa_select(FlashcardModel).where(FlashcardModel.document_id == doc_id)
        )
        all_cards = result.scalars().all()
    assert len(all_cards) == 4


async def test_generate_for_uncovered_calls_flashcard_service(test_db):
    """generate_for_uncovered calls FlashcardService.generate once per section_id."""
    _, factory, _ = test_db
    doc_id = "doc-health-6"
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(section_id=section_id, doc_id=doc_id, heading="Chapter 7"))
        await session.commit()

    mock_svc = AsyncMock()
    mock_svc.generate = AsyncMock(return_value=[])

    with patch(
        "app.services.flashcard.get_flashcard_service", return_value=mock_svc
    ):
        async with factory() as session:
            svc = DeckHealthService()
            total = await svc.generate_for_uncovered(doc_id, [section_id], session)

    mock_svc.generate.assert_called_once()
    call_kwargs = mock_svc.generate.call_args
    assert call_kwargs.kwargs.get("section_heading") == "Chapter 7" or (
        len(call_kwargs.args) >= 3 and call_kwargs.args[2] == "Chapter 7"
    )
    assert total == 0  # mock returns empty list
