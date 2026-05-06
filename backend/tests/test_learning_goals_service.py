"""S210: unit tests for LearningGoalsService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    FlashcardModel,
    NoteModel,
    PomodoroSessionModel,
    QAHistoryModel,
    ReviewEventModel,
)
from app.services.goal_service import (
    GoalNotFound,
    InvalidGoalType,
    InvalidTargetUnit,
    LearningGoalsService,
    SessionNotFound,
)


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

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    *,
    goal_id: str | None,
    surface: str,
    status: str = "completed",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    focus_minutes: int = 25,
) -> PomodoroSessionModel:
    started = started_at or datetime.now(UTC) - timedelta(minutes=30)
    completed = completed_at or started + timedelta(minutes=focus_minutes)
    return PomodoroSessionModel(
        id=str(uuid.uuid4()),
        started_at=started,
        completed_at=completed,
        focus_minutes=focus_minutes,
        break_minutes=5,
        status=status,
        surface=surface,
        goal_id=goal_id,
        created_at=started,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_goal(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Master Stoicism deck",
            goal_type="recall",
            target_value=50,
            target_unit="cards",
            deck_id="stoicism",
        )
        assert goal.status == "active"
        assert goal.goal_type == "recall"
        assert goal.target_value == 50
        assert goal.deck_id == "stoicism"
        fetched = await svc.get_goal(goal.id)
        assert fetched is not None
        assert fetched.id == goal.id


@pytest.mark.asyncio
async def test_create_invalid_goal_type_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        with pytest.raises(InvalidGoalType):
            await svc.create_goal(title="bad", goal_type="walk")


@pytest.mark.asyncio
async def test_create_invalid_target_unit_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        with pytest.raises(InvalidTargetUnit):
            await svc.create_goal(
                title="Bad unit", goal_type="read", target_unit="lightyears"
            )


@pytest.mark.asyncio
async def test_create_empty_title_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        with pytest.raises(ValueError):
            await svc.create_goal(title="   ", goal_type="read")


@pytest.mark.asyncio
async def test_list_goals_status_filter(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        a = await svc.create_goal(title="A", goal_type="read")
        b = await svc.create_goal(title="B", goal_type="recall")
        await svc.archive_goal(b.id)

        active = await svc.list_goals("active")
        archived = await svc.list_goals("archived")
        all_goals = await svc.list_goals(None)

        assert {g.id for g in active} == {a.id}
        assert {g.id for g in archived} == {b.id}
        assert {g.id for g in all_goals} == {a.id, b.id}


@pytest.mark.asyncio
async def test_update_goal_only_mutable_fields(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Old", goal_type="write", target_value=10, target_unit="notes"
        )
        updated = await svc.update_goal(
            goal.id,
            title="New",
            description="updated description",
            target_value=20,
            target_unit="notes",
        )
        assert updated.title == "New"
        assert updated.description == "updated description"
        assert updated.target_value == 20
        # goal_type is immutable -- not a parameter to update_goal
        assert updated.goal_type == "write"


@pytest.mark.asyncio
async def test_update_unknown_goal_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        with pytest.raises(GoalNotFound):
            await svc.update_goal("no-such-id", title="anything")


@pytest.mark.asyncio
async def test_archive_and_complete(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        a = await svc.create_goal(title="archive-me", goal_type="read")
        archived = await svc.archive_goal(a.id)
        assert archived.status == "archived"

        c = await svc.create_goal(title="complete-me", goal_type="read")
        completed = await svc.complete_goal(c.id)
        assert completed.status == "completed"
        assert completed.completed_at is not None


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_and_unlink_session(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(title="g", goal_type="read")
        sess = _make_session(goal_id=None, surface="read", status="active")
        db.add(sess)
        await db.commit()

        linked = await svc.link_session(goal.id, sess.id)
        assert linked.goal_id == goal.id

        unlinked = await svc.unlink_session(goal.id, sess.id)
        assert unlinked.goal_id is None


@pytest.mark.asyncio
async def test_link_unknown_goal_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        sess = _make_session(goal_id=None, surface="read", status="active")
        db.add(sess)
        await db.commit()
        with pytest.raises(GoalNotFound):
            await svc.link_session("nope", sess.id)


@pytest.mark.asyncio
async def test_link_unknown_session_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(title="g", goal_type="read")
        with pytest.raises(SessionNotFound):
            await svc.link_session(goal.id, "no-session")


# ---------------------------------------------------------------------------
# delete_goal sets goal_id NULL on linked sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_goal_nulls_linked_sessions(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(title="del", goal_type="read")
        sess1 = _make_session(goal_id=goal.id, surface="read")
        sess2 = _make_session(goal_id=goal.id, surface="read")
        db.add_all([sess1, sess2])
        await db.commit()
        sid1, sid2 = sess1.id, sess2.id

    async with factory() as db:
        svc = LearningGoalsService(db)
        ok = await svc.delete_goal(goal.id)
        assert ok is True
        assert await svc.get_goal(goal.id) is None

    # Verify sessions persist with goal_id NULL
    from sqlalchemy import select

    async with factory() as db:
        rows = (
            await db.execute(
                select(PomodoroSessionModel).where(
                    PomodoroSessionModel.id.in_([sid1, sid2])
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(r.goal_id is None for r in rows)


@pytest.mark.asyncio
async def test_delete_unknown_goal_returns_false(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        ok = await svc.delete_goal("no-such")
        assert ok is False


# ---------------------------------------------------------------------------
# compute_progress: studying
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_studying_counts_all_completed_surfaces(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Study broadly",
            goal_type="studying",
            target_value=100,
            target_unit="minutes",
            document_id="doc-1",
            collection_id="collection-1",
        )
        sessions = [
            _make_session(goal_id=goal.id, surface="read", focus_minutes=25),
            _make_session(goal_id=goal.id, surface="write", focus_minutes=20),
            _make_session(goal_id=goal.id, surface="recall", focus_minutes=15),
            _make_session(goal_id=goal.id, surface="explore", focus_minutes=10),
            _make_session(goal_id=goal.id, surface="none", focus_minutes=5),
            _make_session(goal_id=None, surface="read", focus_minutes=99),
            _make_session(
                goal_id=goal.id,
                surface="read",
                status="abandoned",
                focus_minutes=99,
            ),
        ]
        db.add_all(sessions)
        await db.commit()

        out = await svc.compute_progress(goal.id)

    assert out["minutes_focused"] == 75
    assert out["sessions_completed"] == 5
    assert out["surface_minutes"] == {
        "read": 25,
        "write": 20,
        "recall": 15,
        "explore": 10,
        "none": 5,
    }
    assert out["surface_sessions"] == {
        "read": 1,
        "write": 1,
        "recall": 1,
        "explore": 1,
        "none": 1,
    }
    assert out["metadata"] == {
        "document_id": "doc-1",
        "deck_id": None,
        "collection_id": "collection-1",
    }
    assert out["completed_pct"] == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# compute_progress: read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_read_sums_completed_minutes(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Read a book",
            goal_type="read",
            target_value=120,
            target_unit="minutes",
        )
        # Two completed read sessions linked to the goal: 25 + 50 = 75 minutes.
        s1 = _make_session(goal_id=goal.id, surface="read", focus_minutes=25)
        s2 = _make_session(goal_id=goal.id, surface="read", focus_minutes=50)
        # Unlinked completed read session: should NOT count.
        s3 = _make_session(goal_id=None, surface="read", focus_minutes=99)
        # Linked write surface: should count because reading may happen while
        # the learner writes notes from an external source.
        s4 = _make_session(goal_id=goal.id, surface="write", focus_minutes=30)
        # Linked, completed, but abandoned status: should NOT count.
        s5 = _make_session(
            goal_id=goal.id,
            surface="read",
            status="abandoned",
            focus_minutes=99,
        )
        db.add_all([s1, s2, s3, s4, s5])
        await db.commit()

        out = await svc.compute_progress(goal.id)

    assert out["minutes_focused"] == 105
    assert out["sessions_completed"] == 3
    # 105/120 = 87.5
    assert out["completed_pct"] == pytest.approx(87.5)


# ---------------------------------------------------------------------------
# compute_progress: recall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_recall_counts_distinct_cards_in_window(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Master deck",
            goal_type="recall",
            target_value=10,
            target_unit="cards",
            deck_id="d1",
        )

        now = datetime.now(UTC)
        sess = _make_session(
            goal_id=goal.id,
            surface="recall",
            started_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=5),
        )
        db.add(sess)

        # Three flashcards in the deck, plus one NOT in the deck.
        cards = [
            FlashcardModel(
                id=f"c{i}",
                document_id=None,
                question="q",
                answer="a",
                source_excerpt="e",
                deck="d1",
            )
            for i in range(3)
        ]
        cards.append(
            FlashcardModel(
                id="other",
                document_id=None,
                question="q",
                answer="a",
                source_excerpt="e",
                deck="other_deck",
            )
        )
        db.add_all(cards)

        # Reviews inside the session window
        ts_inside = now - timedelta(minutes=15)
        events = [
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id="s",
                flashcard_id="c0",
                rating="good",
                is_correct=True,
                reviewed_at=ts_inside,
            ),
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id="s",
                flashcard_id="c0",  # repeat -- distinct count should still be 1 for c0
                rating="again",
                is_correct=False,
                reviewed_at=ts_inside,
            ),
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id="s",
                flashcard_id="c1",
                rating="good",
                is_correct=True,
                reviewed_at=ts_inside,
            ),
            # Card outside the deck (other_deck) -- excluded by deck filter
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id="s",
                flashcard_id="other",
                rating="good",
                is_correct=True,
                reviewed_at=ts_inside,
            ),
            # Outside the session window -- excluded
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id="s",
                flashcard_id="c2",
                rating="good",
                is_correct=True,
                reviewed_at=now - timedelta(hours=2),
            ),
        ]
        db.add_all(events)
        await db.commit()

        out = await svc.compute_progress(goal.id)

    # Distinct cards in deck d1 inside the window: c0, c1
    assert out["cards_reviewed"] == 2
    # Of those events on deck d1 in window: 2 correct, 1 wrong -> 2/3 = 0.6667
    assert out["avg_retention"] == pytest.approx(0.6667, abs=1e-3)
    assert out["sessions_completed"] == 1
    # 2/10 = 20.0
    assert out["completed_pct"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_progress_recall_no_sessions_returns_zero(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="empty", goal_type="recall", target_value=10, deck_id="d1"
        )
        out = await svc.compute_progress(goal.id)
    assert out["cards_reviewed"] == 0
    assert out["avg_retention"] is None
    assert out["sessions_completed"] == 0


# ---------------------------------------------------------------------------
# compute_progress: write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_write_counts_notes_in_session_window(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Write notes",
            goal_type="write",
            target_value=5,
            target_unit="notes",
        )

        now = datetime.now(UTC)
        # Two completed write sessions in two distinct windows.
        s1 = _make_session(
            goal_id=goal.id,
            surface="write",
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=2) + timedelta(minutes=30),
        )
        s2 = _make_session(
            goal_id=goal.id,
            surface="write",
            started_at=now - timedelta(minutes=30),
            completed_at=now,
        )
        # Linked but wrong surface -- excluded.
        s3 = _make_session(goal_id=goal.id, surface="read")
        db.add_all([s1, s2, s3])

        # Two notes inside s1's window, one inside s2, one outside both.
        in_s1 = now - timedelta(hours=2) + timedelta(minutes=10)
        in_s2 = now - timedelta(minutes=15)
        outside = now - timedelta(hours=3)
        notes = [
            NoteModel(
                id=f"n{i}",
                document_id=None,
                content="x",
                created_at=ts,
                updated_at=ts,
            )
            for i, ts in enumerate([in_s1, in_s1, in_s2, outside])
        ]
        db.add_all(notes)
        await db.commit()

        out = await svc.compute_progress(goal.id)

    assert out["notes_created"] == 3
    assert out["sessions_completed"] == 2
    assert out["completed_pct"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# compute_progress: explore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_explore_counts_qa_turns_in_session_window(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(
            title="Explore",
            goal_type="explore",
            target_value=4,
            target_unit="turns",
        )

        now = datetime.now(UTC)
        sess = _make_session(
            goal_id=goal.id,
            surface="explore",
            started_at=now - timedelta(minutes=30),
            completed_at=now,
        )
        db.add(sess)

        # 2 turns inside window, 1 outside.
        in_window = now - timedelta(minutes=10)
        outside = now - timedelta(hours=2)
        turns = [
            QAHistoryModel(
                id=str(uuid.uuid4()),
                document_id=None,
                scope="single",
                question="q",
                answer="a",
                citations=[],
                confidence="medium",
                model_used="test",
                created_at=ts,
            )
            for ts in [in_window, in_window, outside]
        ]
        db.add_all(turns)
        await db.commit()

        out = await svc.compute_progress(goal.id)

    assert out["turns"] == 2
    assert out["sessions_completed"] == 1
    assert out["completed_pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Goalless sessions remain visible to /pomodoro/stats (don't disappear).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goalless_sessions_persist_independently(test_db):
    """Sanity check that the goals feature does not delete or hide sessions
    whose goal_id is NULL. This is the invariant /pomodoro/stats relies on."""
    _engine, factory = test_db
    async with factory() as db:
        svc = LearningGoalsService(db)
        goal = await svc.create_goal(title="g", goal_type="read")

        # Goalless completed session.
        goalless = _make_session(goal_id=None, surface="read")
        # Linked completed session.
        linked = _make_session(goal_id=goal.id, surface="read")
        db.add_all([goalless, linked])
        await db.commit()

    # Delete the goal -- goalless session must persist; linked session must
    # persist with goal_id=NULL (not be deleted).
    async with factory() as db:
        svc = LearningGoalsService(db)
        await svc.delete_goal(goal.id)

    from sqlalchemy import select

    async with factory() as db:
        rows = (await db.execute(select(PomodoroSessionModel))).scalars().all()
        assert len(rows) == 2
        assert all(r.status == "completed" for r in rows)
        assert all(r.goal_id is None for r in rows)
