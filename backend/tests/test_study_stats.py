"""Tests for study statistics and history endpoints."""

import math
import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel, StudySessionModel

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


def _make_card(
    doc_id: str,
    fsrs_stability: float = 5.0,
    fsrs_state: str = "review",
    last_review: datetime | None = None,
    reps: int = 3,
    **kwargs,
) -> FlashcardModel:
    now = datetime.utcnow()
    defaults = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "chunk_id": str(uuid.uuid4()),
        "question": "Question?",
        "answer": "Answer.",
        "source_excerpt": "Excerpt.",
        "fsrs_state": fsrs_state,
        "fsrs_stability": fsrs_stability,
        "fsrs_difficulty": 3.0,
        "due_date": now + timedelta(days=3),
        "reps": reps,
        "lapses": 0,
        "last_review": last_review or now - timedelta(days=1),
        "created_at": now,
    }
    defaults.update(kwargs)
    return FlashcardModel(**defaults)


def _make_session(
    doc_id: str,
    started_at: datetime,
    ended_at: datetime | None = None,
    cards_reviewed: int = 5,
    cards_correct: int = 4,
) -> StudySessionModel:
    return StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=started_at,
        ended_at=ended_at or started_at + timedelta(minutes=15),
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        mode="flashcard",
    )


# ---------------------------------------------------------------------------
# GET /study/stats/{document_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_total_cards(test_db):
    """GET /study/stats returns correct total_cards count."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        for _ in range(4):
            session.add(_make_card(doc_id))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cards"] == 4


@pytest.mark.asyncio
async def test_stats_cards_mastered(test_db):
    """cards_mastered counts only review-state cards with stability > 10."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        # mastered: review + stability > 10
        session.add(_make_card(doc_id, fsrs_stability=12.0, fsrs_state="review"))
        session.add(_make_card(doc_id, fsrs_stability=15.0, fsrs_state="review"))
        # not mastered: review but stability <= 10
        session.add(_make_card(doc_id, fsrs_stability=8.0, fsrs_state="review"))
        # not mastered: learning state
        session.add(_make_card(doc_id, fsrs_stability=12.0, fsrs_state="learning"))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    assert resp.json()["cards_mastered"] == 2


@pytest.mark.asyncio
async def test_stats_avg_retention(test_db):
    """avg_retention uses e^(-days_since_review / stability)."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # 1 card: reviewed 2 days ago, stability=10 → retention = e^(-2/10) ≈ 0.8187
    async with factory() as session:
        session.add(
            _make_card(
                doc_id,
                fsrs_stability=10.0,
                last_review=now - timedelta(days=2),
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    avg_ret = resp.json()["avg_retention"]
    expected = math.exp(-2 / 10)
    assert abs(avg_ret - expected) < 0.01


@pytest.mark.asyncio
async def test_stats_current_streak(test_db):
    """current_streak counts consecutive days back from today/yesterday."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.utcnow()

    async with factory() as session:
        # Sessions on today, yesterday, and 2 days ago → streak = 3
        for days_back in (0, 1, 2):
            t = now - timedelta(days=days_back)
            session.add(
                _make_session(
                    doc_id,
                    started_at=t,
                    ended_at=t + timedelta(minutes=10),
                )
            )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    assert resp.json()["current_streak"] >= 3


@pytest.mark.asyncio
async def test_stats_total_study_time(test_db):
    """total_study_time_minutes sums session durations."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.utcnow()

    async with factory() as session:
        # Two 30-minute sessions → total = 60 minutes
        for i in range(2):
            t = now - timedelta(hours=i)
            session.add(
                _make_session(
                    doc_id,
                    started_at=t,
                    ended_at=t + timedelta(minutes=30),
                )
            )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    assert abs(resp.json()["total_study_time_minutes"] - 60.0) < 0.1


@pytest.mark.asyncio
async def test_stats_empty_document(test_db):
    """Stats for a document with no cards returns zeros."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cards"] == 0
    assert data["cards_mastered"] == 0
    assert data["avg_retention"] == 0.0
    assert data["current_streak"] == 0
    assert data["per_section_stability"] == []
    assert data["all_card_stabilities"] == []


@pytest.mark.asyncio
async def test_stats_all_card_stabilities(test_db):
    """all_card_stabilities returns one entry per card."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_card(doc_id, fsrs_stability=4.0))
        session.add(_make_card(doc_id, fsrs_stability=7.5))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/stats/{doc_id}")

    assert resp.status_code == 200
    stabs = resp.json()["all_card_stabilities"]
    assert len(stabs) == 2
    stab_values = {round(s["stability"], 1) for s in stabs}
    assert stab_values == {4.0, 7.5}


# ---------------------------------------------------------------------------
# GET /study/history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_daily_aggregation(test_db):
    """GET /study/history groups sessions by day."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.utcnow()

    async with factory() as session:
        # Two sessions today
        for _ in range(2):
            session.add(
                _make_session(
                    doc_id,
                    started_at=now.replace(hour=10),
                    ended_at=now.replace(hour=10) + timedelta(minutes=20),
                    cards_reviewed=5,
                )
            )
        # One session yesterday
        yesterday = now - timedelta(days=1)
        session.add(
            _make_session(
                doc_id,
                started_at=yesterday,
                ended_at=yesterday + timedelta(minutes=10),
                cards_reviewed=3,
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/history?document_id={doc_id}&days=7")

    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 2

    today_str = now.date().isoformat()
    today_entry = next((h for h in history if h["date"] == today_str), None)
    assert today_entry is not None
    assert today_entry["cards_reviewed"] == 10  # 2 sessions × 5


@pytest.mark.asyncio
async def test_history_respects_days_filter(test_db):
    """GET /study/history?days=7 excludes sessions older than 7 days."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.utcnow()

    async with factory() as session:
        # Recent session (2 days ago)
        recent = now - timedelta(days=2)
        session.add(
            _make_session(doc_id, started_at=recent, ended_at=recent + timedelta(minutes=10))
        )
        # Old session (10 days ago)
        old = now - timedelta(days=10)
        session.add(
            _make_session(doc_id, started_at=old, ended_at=old + timedelta(minutes=10))
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/history?document_id={doc_id}&days=7")

    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 1


@pytest.mark.asyncio
async def test_history_empty(test_db):
    """GET /study/history returns empty list when no sessions exist."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/study/history?document_id={doc_id}&days=30")

    assert resp.status_code == 200
    assert resp.json() == []
