"""A card's schedule is an append-only log of what the scheduler produced (#453).

A phone reviews offline; merging its reviews later means replaying them from where the two
devices diverged, which needs every state a card passed through. Reviews are logged by the
scheduler with their rating, everything else that moves a schedule by trigger.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db_init import init_database
from app.main import app
from app.models import CardStateEventModel, FlashcardModel, ReviewEventModel, StudySessionModel
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.study_repo import StudyRepo
from app.services import devices
from app.services.deck_health import get_deck_health_service
from tests.factories import make_card, make_document
from tests.test_drop_content_type_migration import _migrate

DOC = "doc-log"
PHONE = {"X-Forwarded-For": "10.0.0.5"}
BEFORE = "bd9cb257888e"


@pytest.fixture
async def client(memory_db):
    devices._active_code = None
    devices._attempts.clear()
    async with memory_db.factory() as session:
        session.add(make_document(id=DOC))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c


async def _log(memory_db, card_id: str) -> list[CardStateEventModel]:
    async with memory_db.factory() as session:
        rows = await session.execute(
            select(CardStateEventModel)
            .where(CardStateEventModel.flashcard_id == card_id)
            .order_by(CardStateEventModel.id)
        )
        return list(rows.scalars())


async def _card(memory_db, **fields) -> str:
    card = make_card(document_id=DOC, **fields)
    async with memory_db.factory() as session:
        session.add(card)
        await session.commit()
    return card.id


async def test_each_review_is_logged_once_with_what_the_scheduler_produced(client, memory_db):
    card_id = await _card(memory_db, fsrs_state="new", due_date=datetime.now(UTC))
    code = (await client.post("/devices/pairing-code")).json()["code"]
    token = (
        await client.post("/devices/pair", json={"code": code, "name": "phone"}, headers=PHONE)
    ).json()["token"]
    device = {**PHONE, "Authorization": f"Bearer {token}"}

    for rating, seq in (("good", 7), ("good", 8)):
        resp = await client.post(
            f"/flashcards/{card_id}/review",
            json={"rating": rating, "client_seq": seq},
            headers=device,
        )
        assert resp.status_code == 200, resp.text

    log = await _log(memory_db, card_id)
    assert [(e.kind, e.rating, e.client_seq) for e in log] == [
        ("created", None, None),
        ("review", "good", 7),
        ("review", "good", 8),
    ]
    assert log[1].device_id is not None and log[1].device_id == log[2].device_id
    async with memory_db.factory() as session:
        card = await session.get(FlashcardModel, card_id)
    last = log[-1]
    assert (last.state, last.step, last.due_date, last.reps) == (
        card.fsrs_state,
        card.fsrs_step,
        card.due_date,
        card.reps,
    )
    assert last.state == "review"


async def test_a_review_and_its_session_event_commit_together(client, memory_db):
    card_id = await _card(memory_db, fsrs_state="new", due_date=datetime.now(UTC))
    async with memory_db.factory() as session:
        study = StudySessionModel(id=str(uuid.uuid4()), document_id=DOC, mode="flashcard")
        session.add(study)
        await session.commit()
    resp = await client.post(
        f"/flashcards/{card_id}/review", json={"rating": "again", "session_id": study.id}
    )
    assert resp.status_code == 200, resp.text
    async with memory_db.factory() as session:
        events = (await session.execute(select(ReviewEventModel))).scalars().all()
    assert [(e.flashcard_id, e.rating) for e in events] == [(card_id, "again")]

    missing = await client.post("/flashcards/missing/review", json={"rating": "good"})
    assert missing.status_code == 404


async def test_changes_that_are_not_reviews_are_logged_by_trigger(client, memory_db):
    held = await _card(memory_db, fsrs_state="held")
    mastered = await _card(
        memory_db, fsrs_state="review", fsrs_stability=400.0, last_review=datetime(2026, 1, 1)
    )
    async with memory_db.factory() as session:
        assert await FlashcardRepo(session).release_held([held]) == 1
        assert await get_deck_health_service().archive_mastered(DOC, session) == 1

    assert [(e.kind, e.state) for e in await _log(memory_db, held)] == [
        ("created", "held"),
        ("state", "new"),
    ]
    assert [(e.kind, e.state) for e in await _log(memory_db, mastered)] == [
        ("created", "review"),
        ("state", "archived"),
    ]


async def test_deleting_a_session_keeps_the_cards_log(client, memory_db):
    card_id = await _card(memory_db, fsrs_state="new", due_date=datetime.now(UTC))
    async with memory_db.factory() as session:
        study = StudySessionModel(id=str(uuid.uuid4()), document_id=DOC, mode="flashcard")
        session.add(study)
        await session.commit()
    await client.post(
        f"/flashcards/{card_id}/review", json={"rating": "good", "session_id": study.id}
    )
    async with memory_db.factory() as session:
        await StudyRepo(session).delete_session_cascade(study.id)
    assert [e.kind for e in await _log(memory_db, card_id)] == ["created", "review"]


async def test_the_upgrade_logs_each_card_as_it_stands_and_moves_no_due_date(client, memory_db):
    await init_database(memory_db.engine)  # the shared template is built from the models
    due = datetime(2026, 12, 1, 9, 30)
    async with memory_db.factory() as session:
        for card_id, state, step in (
            ("a", "learning", 1),
            ("b", "review", None),
            ("c", "new", None),
        ):
            session.add(
                make_card(
                    id=card_id,
                    document_id=DOC,
                    fsrs_state=state,
                    fsrs_step=step,
                    fsrs_stability=3.5,
                    fsrs_difficulty=5.0,
                    due_date=due,
                    reps=2,
                )
            )
        await session.commit()
    # Down to before the log: it and its triggers go, the cards stay as a 0.18 library holds them.
    await _migrate(memory_db.engine, BEFORE)
    async with memory_db.engine.begin() as conn:
        tables = {r[0] for r in await conn.execute(text("SELECT name FROM sqlite_master"))}
        assert "card_state_events" not in tables and "card_state_created" not in tables
    await init_database(memory_db.engine)

    async with memory_db.factory() as session:
        log = (await session.execute(select(CardStateEventModel))).scalars().all()
        cards = (await session.execute(select(FlashcardModel))).scalars().all()
    assert sorted((e.flashcard_id, e.kind, e.state, e.step) for e in log) == [
        ("a", "baseline", "learning", 1),
        ("b", "baseline", "review", None),
        ("c", "baseline", "new", None),
    ]
    assert {c.due_date for c in cards} == {due}
    assert all(e.due_date == due and e.stability == 3.5 for e in log)
    assert datetime.now(UTC).replace(tzinfo=None) - max(e.at for e in log) < timedelta(minutes=5)
