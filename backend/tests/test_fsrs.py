"""Tests for FSRS spaced repetition service and study session endpoints."""

import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel
from app.services.fsrs_service import FSRSService

# ---------------------------------------------------------------------------
# Shared test DB fixture
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


def _make_card(
    doc_id: str | None = None,
    card_id: str | None = None,
    fsrs_state: str = "new",
    due_offset_seconds: int = -10,
    **kwargs,
) -> FlashcardModel:
    """Helper to create a FlashcardModel with sensible defaults."""
    now = datetime.utcnow()
    defaults = {
        "id": card_id or str(uuid.uuid4()),
        "document_id": doc_id or str(uuid.uuid4()),
        "chunk_id": str(uuid.uuid4()),
        "question": "What is spaced repetition?",
        "answer": "A learning method that uses increasing intervals.",
        "source_excerpt": "Spaced repetition ...",
        "fsrs_state": fsrs_state,
        "fsrs_stability": 0.0,
        "fsrs_difficulty": 0.0,
        "due_date": now + timedelta(seconds=due_offset_seconds),
        "reps": 0,
        "lapses": 0,
        "created_at": now,
    }
    defaults.update(kwargs)
    return FlashcardModel(**defaults)


# ---------------------------------------------------------------------------
# FSRSService unit tests
# ---------------------------------------------------------------------------


async def test_schedule_good_sets_future_due_date_and_positive_stability(test_db):
    """Reviewing 'good' on a new card sets due_date in the future and stability > 0."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    service = FSRSService()
    async with factory() as session:
        updated = await service.schedule(card.id, "good", session)

    assert updated.fsrs_stability > 0
    assert updated.due_date is not None
    assert updated.due_date > datetime.utcnow()
    assert updated.reps == 1
    assert updated.lapses == 0
    assert updated.last_review is not None


async def test_schedule_again_increments_lapses(test_db):
    """Reviewing 'again' increments lapses and reps."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    service = FSRSService()
    async with factory() as session:
        updated = await service.schedule(card.id, "again", session)

    assert updated.reps == 1
    assert updated.lapses == 1


async def test_schedule_repeated_again_accumulates_lapses(test_db):
    """Multiple 'again' reviews accumulate lapses."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    service = FSRSService()
    for _ in range(3):
        async with factory() as session:
            await service.schedule(card.id, "again", session)

    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.id == card.id)
        )
        final = result.scalar_one()

    assert final.lapses == 3
    assert final.reps == 3


async def test_schedule_raises_for_missing_card(test_db):
    """schedule() raises ValueError when the card ID doesn't exist."""
    _, factory, _ = test_db
    service = FSRSService()
    async with factory() as session:
        with pytest.raises(ValueError, match="not found"):
            await service.schedule("nonexistent-id", "good", session)


async def test_schedule_easy_sets_review_state(test_db):
    """'easy' rating on a new card should transition state to learning or review."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    service = FSRSService()
    async with factory() as session:
        updated = await service.schedule(card.id, "easy", session)

    # After easy on new card, state should be learning or review (not 'new')
    assert updated.fsrs_state in ("learning", "review", "relearning")
    assert updated.fsrs_stability > 0


# ---------------------------------------------------------------------------
# GET /study/due endpoint tests
# ---------------------------------------------------------------------------


async def test_get_due_cards_returns_only_past_due(test_db):
    """GET /study/due returns only cards with due_date <= now."""
    _, factory, _ = test_db
    now = datetime.utcnow()
    past_card = _make_card(due_offset_seconds=-60)          # overdue
    future_card = _make_card(due_offset_seconds=3600)       # not yet due

    async with factory() as session:
        session.add(past_card)
        session.add(future_card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due")

    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert past_card.id in ids
    assert future_card.id not in ids
    _ = now  # used for context


async def test_get_due_cards_filtered_by_document(test_db):
    """GET /study/due?document_id=X returns only cards for that document."""
    _, factory, _ = test_db
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    card_a = _make_card(doc_id=doc_a, due_offset_seconds=-60)
    card_b = _make_card(doc_id=doc_b, due_offset_seconds=-60)

    async with factory() as session:
        session.add(card_a)
        session.add(card_b)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/due?document_id={doc_a}")

    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert card_a.id in ids
    assert card_b.id not in ids


# ---------------------------------------------------------------------------
# POST /flashcards/{id}/review endpoint tests
# ---------------------------------------------------------------------------


async def test_review_endpoint_good_rating(test_db):
    """POST /flashcards/{id}/review with 'good' returns updated card."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/flashcards/{card.id}/review", json={"rating": "good"}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == card.id
    assert data["reps"] == 1
    assert data["lapses"] == 0


async def test_review_endpoint_again_increases_lapses(test_db):
    """POST /flashcards/{id}/review with 'again' increments lapses."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/flashcards/{card.id}/review", json={"rating": "again"}
        )

    assert resp.status_code == 200
    assert resp.json()["lapses"] == 1


async def test_review_endpoint_404_for_missing_card(test_db):
    """POST /flashcards/{id}/review returns 404 for a non-existent card."""
    _, _factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/flashcards/nonexistent-card/review", json={"rating": "good"}
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Study session endpoint tests
# ---------------------------------------------------------------------------


async def test_start_session_creates_row(test_db):
    """POST /study/sessions/start creates a study session and returns its ID."""
    _, _factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/study/sessions/start", json={"mode": "flashcard", "document_id": None}
        )

    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["mode"] == "flashcard"
    assert data["ended_at"] is None
    assert data["cards_reviewed"] == 0


async def test_start_session_with_document_id(test_db):
    """POST /study/sessions/start accepts optional document_id."""
    _, _factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/study/sessions/start", json={"mode": "flashcard", "document_id": doc_id}
        )

    assert resp.status_code == 201
    assert resp.json()["document_id"] == doc_id


async def test_end_session_sets_ended_at(test_db):
    """POST /study/sessions/{id}/end sets ended_at and returns summary."""
    _, factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_resp = await client.post(
            "/study/sessions/start", json={"mode": "flashcard"}
        )
        session_id = start_resp.json()["id"]

        end_resp = await client.post(f"/study/sessions/{session_id}/end")

    assert end_resp.status_code == 200
    data = end_resp.json()
    assert data["session_id"] == session_id
    assert data["ended_at"] is not None
    assert data["cards_reviewed"] == 0
    _ = factory  # used for context


async def test_end_session_tallies_review_events(test_db):
    """POST /study/sessions/{id}/end counts correct/incorrect from review events."""
    _, factory, _ = test_db
    card1 = _make_card()
    card2 = _make_card()

    async with factory() as session:
        session.add(card1)
        session.add(card2)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Start session
        start_resp = await client.post("/study/sessions/start", json={"mode": "flashcard"})
        session_id = start_resp.json()["id"]

        # Review cards with this session_id
        await client.post(
            f"/flashcards/{card1.id}/review",
            json={"rating": "good", "session_id": session_id},
        )
        await client.post(
            f"/flashcards/{card2.id}/review",
            json={"rating": "again", "session_id": session_id},
        )

        # End session
        end_resp = await client.post(f"/study/sessions/{session_id}/end")

    assert end_resp.status_code == 200
    data = end_resp.json()
    assert data["cards_reviewed"] == 2
    assert data["cards_correct"] == 1  # 'good'=correct, 'again'=incorrect


async def test_end_session_404_for_missing_session(test_db):
    """POST /study/sessions/{id}/end returns 404 for unknown session."""
    _, _factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/study/sessions/nonexistent-id/end")

    assert resp.status_code == 404
