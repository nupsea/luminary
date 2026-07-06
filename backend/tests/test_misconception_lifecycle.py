from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import FlashcardModel, MisconceptionModel
from app.services.fsrs_service import FSRSService
from app.services.misconceptions import get_stats, resolve_for_flashcard, resolve_on_review


@pytest.fixture
async def session_factory():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _card(card_id: str = "card-1") -> FlashcardModel:
    return FlashcardModel(id=card_id, question="q", answer="a", source_excerpt="s")


def _misconception(card_id: str = "card-1", status: str = "open") -> MisconceptionModel:
    return MisconceptionModel(
        id=str(uuid.uuid4()),
        document_id="doc-1",
        flashcard_id=card_id,
        user_answer="wrong",
        error_type="misconception",
        correction_note="note",
        status=status,
    )


async def _open_count(session, card_id: str) -> int:
    rows = (
        (
            await session.execute(
                select(MisconceptionModel).where(
                    MisconceptionModel.flashcard_id == card_id,
                    MisconceptionModel.status == "open",
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


@pytest.mark.asyncio
async def test_good_review_resolves_open_misconceptions(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card())
        session.add(_misconception())
        session.add(_misconception())
        await session.commit()

        await FSRSService().schedule("card-1", "good", session)

        rows = (
            (
                await session.execute(
                    select(MisconceptionModel).where(MisconceptionModel.flashcard_id == "card-1")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert all(r.status == "resolved" for r in rows)
        assert all(r.resolved_at is not None for r in rows)


@pytest.mark.asyncio
async def test_again_review_keeps_misconceptions_open(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card())
        session.add(_misconception())
        await session.commit()

        await FSRSService().schedule("card-1", "again", session)

        assert await _open_count(session, "card-1") == 1


@pytest.mark.asyncio
async def test_resolution_scoped_to_flashcard(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("card-1"))
        session.add(_card("card-2"))
        session.add(_misconception("card-1"))
        session.add(_misconception("card-2"))
        await session.commit()

        await FSRSService().schedule("card-1", "easy", session)

        assert await _open_count(session, "card-1") == 0
        assert await _open_count(session, "card-2") == 1


@pytest.mark.asyncio
async def test_hard_rating_does_not_resolve(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card())
        session.add(_misconception())
        await session.commit()

        assert await resolve_on_review(session, "card-1", "hard") == 0
        assert await _open_count(session, "card-1") == 1


@pytest.mark.asyncio
async def test_already_resolved_rows_untouched(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card())
        session.add(_misconception(status="resolved"))
        await session.commit()

        assert await resolve_for_flashcard(session, "card-1") == 0


@pytest.mark.asyncio
async def test_get_stats_counts_by_status_and_recency(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card())
        session.add(_misconception())
        old = _misconception(status="resolved")
        old.resolved_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60)
        recent = _misconception(status="resolved")
        recent.resolved_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        session.add_all([old, recent])
        await session.commit()

        assert await get_stats(session) == {
            "open_count": 1,
            "resolved_count": 2,
            "resolved_last_30d": 1,
        }
