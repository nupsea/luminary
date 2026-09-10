"""Replacing a deck takes its runs with it, and leaves the learner record alone.

Session History kept rows for runs whose every card had been replaced. Such a
row cannot be entered: I-47 counts only planned cards that still exist, so it
reports nothing planned and nothing outstanding, and its stored explanations
render against a blank question because the results join to the card is outer.

The line the purge must not cross is the review event. It records a review that
happened; streaks, active days and 30-day accuracy read it. Deleting a run may
not rewrite the history of the days it was studied -- the rule
`flashcard_repo._CARD_CHILD_TABLES` and
`document_deletion_service._LEARNER_RECORD_TABLES` already state.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    FlashcardModel,
    ReviewEventModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.repos.study_repo import StudyRepo
from app.services.flashcard import FlashcardService

_T0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


@pytest.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'purge.db'}")
    await create_all_tables(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _card(question: str, document_id: str = "doc-1") -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        chunk_id="chunk-0",
        question=question,
        answer="a",
        source_excerpt="",
        difficulty="medium",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        reps=0,
        lapses=0,
        source_chunk_ids=["chunk-0"],
    )


def _run(
    plan: list[str] | None,
    *,
    document_id: str | None = "doc-1",
    collection_id: str | None = None,
    mode: str = "teachback",
):
    return StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        collection_id=collection_id,
        started_at=_T0,
        ended_at=None,
        cards_reviewed=0,
        cards_correct=0,
        mode=mode,
        planned_card_ids=plan,
    )


def _review(card_id: str, session_id: str) -> ReviewEventModel:
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id=session_id,
        flashcard_id=card_id,
        rating="good",
        is_correct=True,
        reviewed_at=_T0,
    )


async def test_a_run_whose_plan_is_gone_is_removed(factory):
    async with factory() as session:
        card = _card("q1")
        run = _run([card.id])
        session.add_all([card, run])
        await session.commit()

        await session.delete(card)
        await session.commit()

        removed = await StudyRepo(session).purge_runs_without_live_cards(document_ids=["doc-1"])
        rows = (await session.execute(select(StudySessionModel.id))).all()

    assert removed == 1
    assert rows == []


async def test_a_run_with_one_card_left_is_kept(factory):
    """The section-scoped replace. Taking the document's other runs with it is
    the difference between a scoped control and a destructive one."""
    async with factory() as session:
        replaced, survivor = _card("q1"), _card("q2")
        run = _run([replaced.id, survivor.id])
        session.add_all([replaced, survivor, run])
        await session.commit()

        await session.delete(replaced)
        await session.commit()

        removed = await StudyRepo(session).purge_runs_without_live_cards(document_ids=["doc-1"])
        rows = (await session.execute(select(StudySessionModel.id))).all()

    assert removed == 0
    assert [r[0] for r in rows] == [run.id]


async def test_a_run_that_never_had_a_plan_is_left_alone(factory):
    """An empty plan was not built on these cards, so replacing them does not
    make it dead -- and a run being prepared right now has one for a moment."""
    async with factory() as session:
        session.add(_run(None))
        await session.commit()
        removed = await StudyRepo(session).purge_runs_without_live_cards(document_ids=["doc-1"])
        rows = (await session.execute(select(StudySessionModel.id))).all()

    assert removed == 0
    assert len(rows) == 1


async def test_another_document_s_runs_are_untouched(factory):
    async with factory() as session:
        mine, theirs = _card("q1"), _card("q2", document_id="doc-2")
        session.add_all([mine, theirs, _run([mine.id]), _run([theirs.id], document_id="doc-2")])
        await session.commit()

        await session.delete(mine)
        await session.delete(theirs)
        await session.commit()

        removed = await StudyRepo(session).purge_runs_without_live_cards(document_ids=["doc-1"])
        rows = (await session.execute(select(StudySessionModel.document_id))).all()

    assert removed == 1
    assert [r[0] for r in rows] == ["doc-2"]


async def test_the_review_events_of_a_purged_run_survive_it(factory):
    """The one thing the purge may not take. A day the learner studied stays
    studied after the cards are replaced."""
    async with factory() as session:
        card = _card("q1")
        run = _run([card.id])
        session.add_all([card, run])
        await session.commit()
        session.add(_review(card.id, run.id))
        await session.commit()

        await session.delete(card)
        await session.commit()
        await StudyRepo(session).purge_runs_without_live_cards(document_ids=["doc-1"])

        events = (await session.execute(select(ReviewEventModel.session_id))).all()

    assert [e[0] for e in events] == [run.id]


async def test_a_purged_run_takes_its_teachback_results(factory):
    """They are the verdicts on questions nobody can see any more."""
    async with factory() as session:
        card = _card("q1")
        run = _run([card.id])
        session.add_all([card, run])
        await session.commit()
        session.add(
            TeachbackResultModel(
                id=str(uuid.uuid4()),
                flashcard_id=card.id,
                user_explanation="...",
                score=70,
                correct_points=[],
                missing_points=[],
                misconceptions=[],
                status="complete",
                session_id=run.id,
                created_at=_T0,
            )
        )
        await session.commit()

        await session.delete(card)
        await session.commit()
        await StudyRepo(session).purge_runs_without_live_cards(document_ids=["doc-1"])

        results = (await session.execute(select(TeachbackResultModel.id))).all()

    assert results == []


async def test_regenerate_removes_the_runs_and_reports_how_many(factory):
    """The wiring: every door to a replacement is one backend call, so the purge
    belongs behind it rather than in each client."""
    async with factory() as session:
        old = _card("q1")
        run = _run([old.id])
        session.add_all([old, run])
        await session.commit()
        session.add(_review(old.id, run.id))
        await session.commit()

        service = FlashcardService()

        async def fake_generate(**_kwargs):
            fresh = _card("fresh")
            session.add(fresh)
            await session.commit()
            return [fresh]

        service.generate = fake_generate  # type: ignore[method-assign]
        result = await service.regenerate(session, document_id="doc-1")

        runs = (await session.execute(select(StudySessionModel.id))).all()
        events = (await session.execute(select(ReviewEventModel.id))).all()

    assert result.sessions_removed == 1
    assert runs == []
    assert len(events) == 1


async def test_a_kept_deck_keeps_its_runs(factory):
    """Nothing was deleted, so nothing is orphaned."""
    async with factory() as session:
        old = _card("q1")
        run = _run([old.id])
        session.add_all([old, run])
        await session.commit()

        service = FlashcardService()

        async def fake_generate(**_kwargs):
            return []

        service.generate = fake_generate  # type: ignore[method-assign]
        result = await service.regenerate(session, document_id="doc-1")

        runs = (await session.execute(select(StudySessionModel.id))).all()

    assert result.kept_previous is True
    assert result.sessions_removed == 0
    assert [r[0] for r in runs] == [run.id]


# -- the spill: a collection run plans several documents' cards at once -------


async def test_a_collection_run_the_replacement_emptied_goes_too(factory):
    """A document replace never names the collection, and still empties its run."""
    async with factory() as session:
        card = _card("q1")
        run = _run([card.id], document_id=None, collection_id="coll-1")
        session.add_all([card, run])
        await session.commit()

        await session.delete(card)
        await session.commit()

        removed = await StudyRepo(session).purge_runs_without_live_cards(
            document_ids=["doc-1"], deleted_card_ids=[card.id]
        )
        rows = (await session.execute(select(StudySessionModel.id))).all()

    assert removed == 1
    assert rows == []


async def test_a_collection_run_with_another_document_s_card_left_is_kept(factory):
    async with factory() as session:
        gone = _card("q1")
        elsewhere = _card("q2", document_id="doc-2")
        run = _run([gone.id, elsewhere.id], document_id=None, collection_id="coll-1")
        session.add_all([gone, elsewhere, run])
        await session.commit()
        run_id = run.id

        await session.delete(gone)
        await session.commit()

        removed = await StudyRepo(session).purge_runs_without_live_cards(
            document_ids=["doc-1"], deleted_card_ids=[gone.id]
        )
        rows = (await session.execute(select(StudySessionModel.id))).scalars().all()

    assert removed == 0
    assert list(rows) == [run_id]


async def test_a_collection_run_this_delete_never_touched_is_left_alone(factory):
    """Dead already, and none of its cards are the ones this call deleted.

    Cleaning it up here would delete a row from a list nobody asked about.
    """
    async with factory() as session:
        mine = _card("q1")
        stale = _run(["long-gone-card"], document_id=None, collection_id="coll-9")
        session.add_all([mine, stale])
        await session.commit()
        stale_id = stale.id

        await session.delete(mine)
        await session.commit()

        removed = await StudyRepo(session).purge_runs_without_live_cards(
            document_ids=["doc-1"], deleted_card_ids=[mine.id]
        )
        rows = (await session.execute(select(StudySessionModel.id))).scalars().all()

    assert removed == 0
    assert list(rows) == [stale_id]
