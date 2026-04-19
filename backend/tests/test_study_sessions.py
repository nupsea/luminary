"""Tests for GET /study/sessions and GET /study/sessions/{id}/cards endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel, ReviewEventModel, StudySessionModel

# ---------------------------------------------------------------------------
# Test DB fixture
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


def _make_session(
    doc_id: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    cards_reviewed: int = 5,
    cards_correct: int = 4,
    accuracy_pct: float | None = None,
) -> StudySessionModel:
    now = datetime.now(UTC)
    return StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=started_at or now,
        ended_at=ended_at or (started_at or now) + timedelta(minutes=15),
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        accuracy_pct=accuracy_pct,
        mode="flashcard",
    )


def _make_card(doc_id: str) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=str(uuid.uuid4()),
        question="What is the capital of France?",
        answer="Paris.",
        source_excerpt="Excerpt.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


def _make_review_event(
    session_id: str,
    flashcard_id: str,
    rating: str = "good",
    is_correct: bool = True,
) -> ReviewEventModel:
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id=session_id,
        flashcard_id=flashcard_id,
        rating=rating,
        is_correct=is_correct,
        reviewed_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# GET /study/sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_empty(test_db):
    """Returns empty list with total=0 when no sessions exist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


@pytest.mark.asyncio
async def test_list_sessions_pagination(test_db):
    """Returns page_size items with correct total when there are more sessions."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with factory() as session:
        for i in range(5):
            session.add(_make_session(doc_id=doc_id, started_at=now - timedelta(hours=i)))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions?page=1&page_size=2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


@pytest.mark.asyncio
async def test_list_sessions_sorted_desc(test_db):
    """Sessions are returned newest first."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    t_old = now - timedelta(hours=5)
    t_new = now - timedelta(hours=1)

    async with factory() as session:
        session.add(_make_session(doc_id=doc_id, started_at=t_old))
        session.add(_make_session(doc_id=doc_id, started_at=t_new))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # First item should be the more recent one
    assert items[0]["started_at"] > items[1]["started_at"]


@pytest.mark.asyncio
async def test_list_sessions_document_filter(test_db):
    """document_id query param filters sessions by document."""
    _, factory, _ = test_db
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_session(doc_id=doc_a))
        session.add(_make_session(doc_id=doc_a))
        session.add(_make_session(doc_id=doc_b))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions?document_id={doc_a}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(item["document_id"] == doc_a for item in data["items"])


@pytest.mark.asyncio
async def test_list_sessions_accuracy_pct(test_db):
    """end_session stores accuracy_pct; GET /study/sessions returns it."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    # Create session with accuracy_pct already computed (simulates end_session result)
    async with factory() as session:
        session.add(
            _make_session(
                doc_id=doc_id,
                cards_reviewed=10,
                cards_correct=7,
                accuracy_pct=70.0,
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["accuracy_pct"] == 70.0
    assert items[0]["cards_reviewed"] == 10
    assert items[0]["cards_correct"] == 7


# ---------------------------------------------------------------------------
# GET /study/sessions/{session_id}/cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_cards_returns_review_events(test_db):
    """GET /study/sessions/{id}/cards returns one entry per review event."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        card1 = _make_card(doc_id)
        card2 = _make_card(doc_id)
        sess = _make_session(doc_id=doc_id)
        session.add(card1)
        session.add(card2)
        session.add(sess)
        await session.flush()

        session.add(_make_review_event(sess.id, card1.id, rating="good", is_correct=True))
        session.add(_make_review_event(sess.id, card2.id, rating="again", is_correct=False))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/{sess.id}/cards")

    assert resp.status_code == 200
    cards = resp.json()
    assert len(cards) == 2
    ratings = {c["rating"] for c in cards}
    assert ratings == {"good", "again"}
    correct_flags = {c["flashcard_id"]: c["is_correct"] for c in cards}
    assert correct_flags[card1.id] is True
    assert correct_flags[card2.id] is False


@pytest.mark.asyncio
async def test_session_cards_404_unknown_session(test_db):
    """GET /study/sessions/{id}/cards returns 404 for unknown session_id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/{uuid.uuid4()}/cards")

    assert resp.status_code == 404
