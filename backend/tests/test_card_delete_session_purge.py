"""Deleting a deck takes the runs it emptied, by every door that deletes cards.

Replacing a deck already did this. "Delete all" did not, so the Study page
answered a deletion by leaving the practice runs it had just emptied in the
history below it -- rows that cannot be entered, because I-47 counts only
planned cards that still exist and none of them do.

The line these tests hold is the review event. It records a review that
happened, and streaks, active days and 30-day accuracy read it. A deletion of
cards may not rewrite the history of the days they were studied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    CollectionMemberModel,
    CollectionModel,
    FlashcardModel,
    ReviewEventModel,
    StudySessionModel,
)

_T0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, session_factory
    yield session_factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _card(cid: str, *, document_id: str | None = "doc-1") -> FlashcardModel:
    return FlashcardModel(
        id=cid,
        document_id=document_id,
        chunk_id="chunk-0",
        question=f"Q {cid}?",
        answer="A real multi-word answer here.",
        source_excerpt="s",
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
    mode: str = "flashcard",
) -> StudySessionModel:
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


async def _run_ids(factory) -> set[str]:
    async with factory() as session:
        return set((await session.execute(select(StudySessionModel.id))).scalars().all())


@pytest.mark.asyncio
async def test_deleting_a_document_s_deck_removes_its_runs_and_says_how_many(factory):
    async with factory() as session:
        session.add_all([_card("c1"), _card("c2"), _run(["c1", "c2"]), _run(["c1"])])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/flashcards/document/doc-1")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2, "sessions_removed": 2}
    assert await _run_ids(factory) == set()


@pytest.mark.asyncio
async def test_the_review_events_of_a_deleted_deck_s_runs_survive(factory):
    async with factory() as session:
        run = _run(["c1"])
        session.add_all(
            [
                _card("c1"),
                run,
                ReviewEventModel(
                    id=str(uuid.uuid4()),
                    session_id=run.id,
                    flashcard_id="c1",
                    rating="good",
                    is_correct=True,
                    reviewed_at=_T0,
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.delete("/flashcards/document/doc-1")

    async with factory() as session:
        events = (await session.execute(select(ReviewEventModel))).scalars().all()
    assert len(events) == 1
    assert events[0].reviewed_at.replace(tzinfo=UTC) == _T0


@pytest.mark.asyncio
async def test_another_document_s_runs_are_left_alone(factory):
    async with factory() as session:
        keep = _run(["c9"], document_id="doc-2")
        session.add_all([_card("c1"), _card("c9", document_id="doc-2"), _run(["c1"]), keep])
        await session.commit()
        keep_id = keep.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/flashcards/document/doc-1")

    assert resp.json()["sessions_removed"] == 1
    assert await _run_ids(factory) == {keep_id}


@pytest.mark.asyncio
async def test_a_bulk_delete_that_leaves_a_card_keeps_the_run(factory):
    async with factory() as session:
        run = _run(["c1", "c2"])
        session.add_all([_card("c1"), _card("c2"), run])
        await session.commit()
        run_id = run.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/flashcards/bulk-delete", json={"ids": ["c1"]})

    assert resp.json() == {"deleted": 1, "sessions_removed": 0}
    assert await _run_ids(factory) == {run_id}


@pytest.mark.asyncio
async def test_a_bulk_delete_that_empties_a_run_removes_it(factory):
    async with factory() as session:
        session.add_all([_card("c1"), _card("c2"), _run(["c1", "c2"])])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/flashcards/bulk-delete", json={"ids": ["c1", "c2"]})

    assert resp.json() == {"deleted": 2, "sessions_removed": 1}
    assert await _run_ids(factory) == set()


@pytest.mark.asyncio
async def test_deleting_the_last_card_of_a_run_removes_it(factory):
    async with factory() as session:
        session.add_all([_card("c1"), _run(["c1"])])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/flashcards/c1")

    assert resp.status_code == 204
    assert await _run_ids(factory) == set()


@pytest.mark.asyncio
async def test_a_collection_delete_removes_the_collection_s_own_run(factory):
    coll_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            CollectionModel(id=coll_id, name="Data Architecture", color="#6366F1", sort_order=0)
        )
        session.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=coll_id,
                member_id="doc-1",
                member_type="document",
            )
        )
        # One run scoped to the collection, one to a document inside it: the
        # same delete empties both, and they are different rows.
        session.add_all(
            [
                _card("c1"),
                _run(["c1"], document_id=None, collection_id=coll_id),
                _run(["c1"]),
            ]
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/flashcards/collection/{coll_id}")

    assert resp.json() == {"deleted": 1, "sessions_removed": 2}
    assert await _run_ids(factory) == set()
