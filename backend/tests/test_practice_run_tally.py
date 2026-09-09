"""The Practice run's arithmetic: one card, one verdict, the latest attempt.

Every number the docked Practice panel shows -- reviewed, passed, the average --
used to count submissions rather than cards, so "Answer this one again" made the
same question appear twice in the summary and averaged a score the learner had
already replaced. A 10 improved to a 45, beside a 90, read as three cards
averaging 48; it is two cards averaging 68.

Also guarded here: only the first attempt on a card reschedules it. A re-answer
is written after the panel has shown the expected answer and the missing points,
so scheduling on it would let material the product supplied set the interval.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    FlashcardModel,
    ReviewEventModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.routers.study import _latest_attempt_per_card, _teachback_tally


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


_T0 = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _attempt(card_id, score, *, minute=0, status="complete", session_id="s1"):
    return TeachbackResultModel(
        id=str(uuid.uuid4()),
        flashcard_id=card_id,
        user_explanation="...",
        score=score,
        correct_points=[],
        missing_points=[],
        misconceptions=[],
        status=status,
        session_id=session_id,
        created_at=_T0 + timedelta(minutes=minute),
    )


def test_the_screenshot_case():
    """Two cards, three attempts: 10 improved to 45, and a 90.

    Counting submissions gave "3 scored, averaging 48" over a run that reviewed
    two cards. The verdicts that stand are 45 and 90.
    """
    rows = [
        _attempt("geometry", 10, minute=0),
        _attempt("simplex", 90, minute=1),
        _attempt("geometry", 45, minute=2),
    ]
    reviewed, correct, accuracy, pending = _teachback_tally(rows)
    assert (reviewed, correct, pending) == (2, 1, 0)
    assert accuracy == 67.5


def test_a_worse_second_attempt_also_stands():
    """Latest, not best. The summary reports where the learner ended up."""
    rows = [_attempt("c1", 90, minute=0), _attempt("c1", 20, minute=1)]
    reviewed, correct, accuracy, _pending = _teachback_tally(rows)
    assert (reviewed, correct, accuracy) == (1, 0, 20.0)


def test_accuracy_is_none_while_a_standing_attempt_is_unscored():
    """Not 0.0, and not a mean of whatever finished: an unscored card is
    unscored, and a run that is still scoring has no average yet."""
    rows = [_attempt("c1", 80, minute=0), _attempt("c2", 0, minute=1, status="pending")]
    reviewed, _correct, accuracy, pending = _teachback_tally(rows)
    assert reviewed == 2
    assert pending == 1
    assert accuracy is None


def test_a_superseded_pending_attempt_does_not_hold_the_run_open():
    """The first attempt errored or stalled and was answered again. The verdict
    that stands is complete, so the run has an average."""
    rows = [
        _attempt("c1", 0, minute=0, status="pending"),
        _attempt("c1", 70, minute=1),
    ]
    reviewed, correct, accuracy, pending = _teachback_tally(rows)
    assert (reviewed, correct, pending, accuracy) == (1, 1, 0, 70.0)


def test_earlier_attempts_are_kept_not_deleted():
    """The record of how the learner got there survives; it is just not the verdict."""
    rows = [_attempt("c1", 10, minute=0), _attempt("c1", 45, minute=1)]
    assert len(rows) == 2
    assert [r.score for r in _latest_attempt_per_card(rows)] == [45]


def _card(doc_id):
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=str(uuid.uuid4()),
        question="What is a vertex?",
        answer="A corner of the feasible region.",
        source_excerpt="The feasible region is a polytope.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


async def test_end_session_counts_cards_not_submissions(test_db):
    """POST /sessions/{id}/end over a re-answered card."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card_a, card_b = _card(doc_id), _card(doc_id)
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        accuracy_pct=None,
        mode="teachback",
        planned_card_ids=[card_a.id, card_b.id],
    )
    async with factory() as session:
        session.add_all([card_a, card_b, sess])
        session.add_all(
            [
                _attempt(card_a.id, 10, minute=0, session_id=sess.id),
                _attempt(card_b.id, 90, minute=1, session_id=sess.id),
                _attempt(card_a.id, 45, minute=2, session_id=sess.id),
            ]
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/study/sessions/{sess.id}/end")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cards_reviewed"] == 2
    assert body["cards_correct"] == 1
    assert body["accuracy_pct"] == 67.5


async def test_only_the_first_attempt_reschedules_the_card(test_db):
    """The re-answer is stored and scored; it does not touch FSRS or add an event."""
    from app.routers.study import _evaluate_teachback_bg

    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _card(doc_id)
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        accuracy_pct=None,
        mode="teachback",
        planned_card_ids=[card.id],
    )
    first = _attempt(card.id, 0, minute=0, status="pending", session_id=sess.id)
    first.flashcard_id = card.id
    second = _attempt(card.id, 0, minute=5, status="pending", session_id=sess.id)
    second.flashcard_id = card.id
    async with factory() as session:
        session.add_all([card, sess, first, second])
        await session.commit()

    from unittest.mock import AsyncMock, patch

    response = (
        '{"score": 85, "correct_points": [], "missing_points": [], '
        '"misconceptions": [], "evidence": "The feasible region is a polytope.", '
        '"accuracy": 85, "completeness": 80, "clarity": 90, "clarity_comment": "Clear."}'
    )
    for tb in (first, second):
        with patch("app.routers.study.get_llm_service") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(return_value=response)
            mock_get_llm.return_value = mock_llm
            await _evaluate_teachback_bg(
                tb_id=tb.id,
                card_id=card.id,
                card_answer=card.answer,
                card_document_id=doc_id,
                card_question=card.question,
                user_explanation="A corner of the region.",
                session_id=sess.id,
            )

    async with factory() as session:
        rows = (
            await session.execute(
                select(TeachbackResultModel).where(
                    TeachbackResultModel.session_id == sess.id
                )
            )
        ).scalars().all()
        events = (
            await session.execute(
                select(ReviewEventModel).where(ReviewEventModel.session_id == sess.id)
            )
        ).scalars().all()
        graded = (
            await session.execute(
                select(FlashcardModel).where(FlashcardModel.id == card.id)
            )
        ).scalar_one()

    # Both attempts scored and stored...
    assert sorted(r.status for r in rows) == ["complete", "complete"]
    # ...but the card was reviewed once.
    assert len(events) == 1
    assert graded.reps == 1


# POST /study/sessions/{id}/cards -- adding questions to a run in progress


async def test_appending_cards_extends_the_planned_queue(test_db):
    """A run is rebuilt from planned_card_ids on every resume, so a card
    generated mid-run has to land here and not only in the client's memory."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    started, added = _card(doc_id), _card(doc_id)
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        accuracy_pct=None,
        mode="teachback",
        planned_card_ids=[started.id],
    )
    async with factory() as session:
        session.add_all([started, added, sess])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/study/sessions/{sess.id}/cards", json={"card_ids": [added.id]}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "session_id": sess.id,
            "added": 1,
            "planned_count": 2,
        }

        remaining = await client.get(f"/study/sessions/{sess.id}/remaining-cards")

    assert remaining.status_code == 200
    body = remaining.json()
    assert body["planned_count"] == 2
    assert {c["id"] for c in body["cards"]} == {started.id, added.id}


async def test_appending_the_same_card_twice_queues_it_once(test_db):
    """Pressing Generate twice, or a retried request, must not put a card in the
    run a second time -- the learner would be asked the same question twice."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _card(doc_id)
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        accuracy_pct=None,
        mode="teachback",
        planned_card_ids=[card.id],
    )
    async with factory() as session:
        session.add_all([card, sess])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/study/sessions/{sess.id}/cards", json={"card_ids": [card.id]}
        )

    assert resp.status_code == 200
    assert resp.json()["added"] == 0
    assert resp.json()["planned_count"] == 1


async def test_appending_an_unknown_card_is_dropped(test_db):
    """A planned id with no card behind it makes remaining-cards return a
    shorter queue than planned_count promises, which reads as a run stuck short
    of its own total."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _card(doc_id)
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        accuracy_pct=None,
        mode="teachback",
        planned_card_ids=[card.id],
    )
    async with factory() as session:
        session.add_all([card, sess])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/study/sessions/{sess.id}/cards",
            json={"card_ids": [str(uuid.uuid4())]},
        )

    assert resp.status_code == 200
    assert resp.json()["added"] == 0
    assert resp.json()["planned_count"] == 1


async def test_appending_to_a_session_that_is_gone_is_a_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/study/sessions/{uuid.uuid4()}/cards", json={"card_ids": []}
        )
    assert resp.status_code == 404


# The model's list fields, normalised where they enter the system


@pytest.mark.parametrize(
    ("label", "raw_value", "expected"),
    [
        ("flat", ["a", "b"], ["a", "b"]),
        # The real one: a nested list took out a whole run's feedback, because
        # GET /teachback/results validates list[str] and answered 500 for the
        # entire batch the panel polls.
        ("nested", [["a", "b"]], ["a", "b"]),
        ("mixed", ["a", ["b", "c"]], ["a", "b", "c"]),
        ("a bare string", "just one", ["just one"]),
        ("numbers", [1, 2], ["1", "2"]),
        ("blank entries dropped", ["a", "", "  "], ["a"]),
        ("missing", None, []),
        ("not a list", {"a": 1}, []),
    ],
)
def test_list_fields_are_normalised_to_strings(label, raw_value, expected):
    from app.routers.study import _parse_teachback_response

    parsed = _parse_teachback_response(
        json.dumps(
            {"accuracy": 50, "completeness": 50, "misconceptions": raw_value}
        )
    )
    assert parsed is not None, label
    assert parsed["misconceptions"] == expected, label


def test_absent_list_fields_become_empty_lists_not_none():
    """Everything downstream is typed list[str]; None is not one of them."""
    from app.routers.study import _parse_teachback_response

    parsed = _parse_teachback_response('{"accuracy": 70, "completeness": 70}')
    assert parsed is not None
    assert parsed["correct_points"] == []
    assert parsed["missing_points"] == []
    assert parsed["misconceptions"] == []


# The recall arm's twin of the teach-back tally (I-46)


def test_a_card_graded_twice_is_one_card_reviewed():
    """`len(events)` counted grades. A run's summary counts cards.

    Same defect as the teach-back arm's "30 of 15 reviewed", one arm over.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import ReviewEventModel
    from app.routers.study import _latest_event_per_card

    now = datetime.now(UTC)
    events = [
        ReviewEventModel(id="e1", session_id="s", flashcard_id="a",
                         is_correct=False, reviewed_at=now),
        ReviewEventModel(id="e2", session_id="s", flashcard_id="a",
                         is_correct=True, reviewed_at=now + timedelta(seconds=30)),
        ReviewEventModel(id="e3", session_id="s", flashcard_id="b",
                         is_correct=True, reviewed_at=now + timedelta(seconds=60)),
    ]

    latest = _latest_event_per_card(events)

    assert len(latest) == 2
    # The grade that stands is the later one: the learner improved on it.
    assert sum(1 for e in latest if e.is_correct) == 2


def test_the_latest_event_wins_regardless_of_query_order():
    from datetime import UTC, datetime, timedelta

    from app.models import ReviewEventModel
    from app.routers.study import _latest_event_per_card

    now = datetime.now(UTC)
    later = ReviewEventModel(id="e2", session_id="s", flashcard_id="a",
                             is_correct=False, reviewed_at=now + timedelta(seconds=30))
    earlier = ReviewEventModel(id="e1", session_id="s", flashcard_id="a",
                               is_correct=True, reviewed_at=now)

    latest = _latest_event_per_card([later, earlier])

    assert [e.id for e in latest] == ["e2"]


async def test_a_replaced_deck_leaves_the_run_no_phantom_progress(test_db):
    """Cards deleted out from under an open run count on NEITHER side of the ratio.

    Reported from the reader: "7 of 8 reviewed" on a document holding three
    cards. Replacing the deck had deleted five of the eight the run planned, and
    the review events for those five stayed behind -- so they counted as done
    while `cards` quietly dropped them, and answered + remaining still summed to
    planned. A learner cannot be shown a card that no longer exists, so it is
    neither progress nor work outstanding.
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    replaced = [_card(doc_id), _card(doc_id)]
    kept = [_card(doc_id), _card(doc_id), _card(doc_id)]
    answered_kept = kept[0]
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        accuracy_pct=None,
        mode="teachback",
        planned_card_ids=[c.id for c in replaced + kept],
    )
    async with factory() as session:
        session.add_all([*replaced, *kept, sess])
        session.add_all(
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id=sess.id,
                flashcard_id=card.id,
                rating="again",
                is_correct=False,
                reviewed_at=_T0 + timedelta(minutes=i),
            )
            for i, card in enumerate([*replaced, answered_kept])
        )
        await session.commit()
        # The replacement: generation writes the new cards, then the old ones go.
        for card in replaced:
            await session.delete(await session.get(FlashcardModel, card.id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/{sess.id}/remaining-cards")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["planned_count"] == 3, "the deck holds three cards, so the run does too"
    assert body["answered_count"] == 1, "only the live card was reviewed"
    assert [c["id"] for c in body["cards"]] == [c.id for c in kept[1:]]
