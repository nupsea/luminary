"""Tests for flashcard search endpoint and FTS5 sync (S184)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel

# ---------------------------------------------------------------------------
# Isolated test DB fixture (same pattern as test_flashcards.py)
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


def _make_flashcard(
    card_id: str | None = None,
    doc_id: str = "doc-1",
    question: str = "What is entanglement?",
    answer: str = "A quantum correlation between particles.",
    **kwargs,
) -> FlashcardModel:
    now = datetime.now(UTC)
    defaults = {
        "id": card_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "chunk_id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "source_excerpt": "Some excerpt.",
        "fsrs_state": "new",
        "fsrs_stability": 0.0,
        "fsrs_difficulty": 0.0,
        "due_date": now,
        "reps": 0,
        "lapses": 0,
        "created_at": now,
    }
    defaults.update(kwargs)
    return FlashcardModel(**defaults)


# ---------------------------------------------------------------------------
# AC8: GET /flashcards/search with query param returns matching cards via FTS5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_query(test_db):
    """Cards inserted into FTS should be found by keyword search."""
    _, factory, _ = test_db

    card = _make_flashcard(
        question="What is quantum entanglement?",
        answer="A mysterious correlation between distant particles.",
    )
    async with factory() as session:
        session.add(card)
        # Sync FTS manually (service helper not called in direct insert)
        await session.execute(
            text(
                "INSERT INTO flashcards_fts(flashcard_id, question, answer) "
                "VALUES (:fid, :q, :a)"
            ),
            {"fid": card.id, "q": card.question, "a": card.answer},
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/flashcards/search", params={"query": "entanglement"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        ids = [item["id"] for item in data["items"]]
        assert card.id in ids


# ---------------------------------------------------------------------------
# AC9: GET /flashcards/search with bloom_level_min=3 returns only L3+ cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_bloom_level_min(test_db):
    """Only cards with bloom_level >= min should be returned."""
    _, factory, _ = test_db

    card_low = _make_flashcard(
        question="Define X",
        answer="X is Y",
        bloom_level=1,
        flashcard_type="definition",
    )
    card_mid = _make_flashcard(
        question="Apply X to Z",
        answer="You apply X by...",
        bloom_level=3,
        flashcard_type="application",
    )
    card_high = _make_flashcard(
        question="Evaluate X vs Y",
        answer="X is better because...",
        bloom_level=5,
        flashcard_type="evaluation",
    )

    async with factory() as session:
        session.add(card_low)
        session.add(card_mid)
        session.add(card_high)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/flashcards/search", params={"bloom_level_min": 3}
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert card_low.id not in ids
        assert card_mid.id in ids
        assert card_high.id in ids


# ---------------------------------------------------------------------------
# AC10: flashcards_fts table is populated on card creation (via service)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_populated_on_create(test_db):
    """When a card is inserted via the service helper, FTS row exists."""
    _, factory, _ = test_db
    from app.services.flashcard import _sync_flashcard_fts

    card = _make_flashcard(
        question="What is recursion?",
        answer="A function that calls itself.",
    )
    async with factory() as session:
        session.add(card)
        await _sync_flashcard_fts(card, session)
        await session.commit()

        # Verify FTS row exists
        row = (
            await session.execute(
                text("SELECT COUNT(*) FROM flashcards_fts")
            )
        ).scalar_one()
        assert row >= 1

        # Verify searchable via MATCH
        match_row = (
            await session.execute(
                text(
                    "SELECT flashcard_id FROM flashcards_fts"
                    " WHERE flashcards_fts MATCH 'recursion'"
                )
            )
        ).first()
        assert match_row is not None
        assert match_row[0] == card.id


# ---------------------------------------------------------------------------
# Additional: search with no params returns 200 + empty or all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_no_params(test_db):
    """GET /flashcards/search with no params returns 200."""
    _, _, _ = test_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/flashcards/search")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data


# ---------------------------------------------------------------------------
# Additional: search by fsrs_state filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_fsrs_state(test_db):
    """Filter by fsrs_state returns only matching cards."""
    _, factory, _ = test_db

    card_new = _make_flashcard(question="Q1", answer="A1", fsrs_state="new")
    card_review = _make_flashcard(question="Q2", answer="A2", fsrs_state="review")

    async with factory() as session:
        session.add(card_new)
        session.add(card_review)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/flashcards/search", params={"fsrs_state": "new"})
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert card_new.id in ids
        assert card_review.id not in ids
