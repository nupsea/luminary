"""Tests for GET /study/due-count endpoint (S118)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import FlashcardModel
from tests.factories import make_card

pytestmark = pytest.mark.usefixtures("card_documents")


def _card(due_date: datetime | None = None) -> FlashcardModel:
    return make_card(
        document_id="doc1",
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
        fsrs_state="review",
        fsrs_stability=1.0,
        fsrs_difficulty=0.5,
        due_date=due_date,
    )


@pytest.mark.asyncio
async def test_due_count_empty_db(test_db):
    """No flashcards -> due_today == 0."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 0


@pytest.mark.asyncio
async def test_due_count_with_due_cards(test_db):
    """Two cards with due_date in the past -> due_today == 2."""
    _, factory, _ = test_db
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(_card(due_date=now - timedelta(days=1)))
        session.add(_card(due_date=now - timedelta(hours=1)))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 2


@pytest.mark.asyncio
async def test_due_count_excludes_future_cards(test_db):
    """Cards with due_date in the future are not counted."""
    _, factory, _ = test_db
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(_card(due_date=now + timedelta(days=7)))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 0


@pytest.mark.asyncio
async def test_due_count_excludes_null_due_date(test_db):
    """Cards with due_date=None (never scheduled) are not counted."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_card(due_date=None))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 0


def _unseen(card_id: str, document_id: str = "doc1", state: str = "new") -> FlashcardModel:
    """A card as every generator writes it: never reviewed, `due_date` now."""
    return make_card(
        id=card_id,
        document_id=document_id,
        question=f"Q {card_id}?",
        answer="A.",
        source_excerpt="A.",
        fsrs_state=state,
        due_date=datetime.now(UTC) - timedelta(minutes=1),
    )


async def _get(path: str, **params):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, params=params)


@pytest.mark.asyncio
async def test_an_unseen_card_due_now_is_new_not_due(test_db):
    """I-83: generators write `due_date=now`; that never makes a card due."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_unseen("fresh"))
        session.add(_card(due_date=datetime.now(UTC) - timedelta(hours=1)))
        await session.commit()
    body = (await _get("/study/due-count")).json()
    assert body["due_today"] == 1
    assert body["new_available"] == 1
    assert body["new_today"] == 1


@pytest.mark.asyncio
async def test_held_and_archived_cards_are_neither_due_nor_new(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_unseen("held", state="held"))
        session.add(_unseen("archived", state="archived"))
        await session.commit()
    body = (await _get("/study/due-count")).json()
    assert (body["due_today"], body["new_available"]) == (0, 0)


@pytest.mark.asyncio
async def test_the_library_queue_takes_new_cards_by_the_daily_budget(test_db):
    from app.models import ReviewEventModel
    from app.services.settings_service import set_new_cards_per_day

    _, factory, _ = test_db
    async with factory() as session:
        await set_new_cards_per_day(session, 3)
        session.add_all([_unseen(f"n{i}") for i in range(6)])
        session.add(_card(due_date=datetime.now(UTC) - timedelta(hours=1)))
        # One card was first reviewed today, so two of the three remain.
        session.add(
            ReviewEventModel(
                id="ev1", session_id="s", flashcard_id="seen", rating="good", is_correct=True
            )
        )
        await session.commit()

    body = (await _get("/study/due-count")).json()
    assert (body["new_per_day"], body["new_today"], body["new_available"]) == (3, 2, 6)

    queue = (await _get("/study/due", limit=50)).json()
    states = [c["fsrs_state"] for c in queue]
    assert states == ["review", "new", "new"]


@pytest.mark.asyncio
async def test_a_chosen_scope_takes_its_new_cards_past_the_budget(test_db):
    from app.services.settings_service import set_new_cards_per_day

    _, factory, _ = test_db
    async with factory() as session:
        await set_new_cards_per_day(session, 1)
        session.add_all([_unseen(f"n{i}") for i in range(4)])
        await session.commit()

    assert (await _get("/study/due-count", document_ids="doc1")).json()["new_today"] == 4
    assert len((await _get("/study/due", document_id="doc1", limit=3)).json()) == 3
    assert len((await _get("/study/due", limit=50)).json()) == 1


@pytest.mark.asyncio
async def test_the_day_starts_at_the_users_midnight():
    from app.services.study_queue import local_day_start

    # 23:30 UTC on the 1st is 08:30 on the 2nd in UTC+9 (JS offset -540).
    now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    assert local_day_start(-540, now) == datetime(2026, 1, 1, 15, 0)
    assert local_day_start(0, now) == datetime(2026, 1, 1, 0, 0)
