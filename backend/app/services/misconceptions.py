import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MisconceptionModel

logger = logging.getLogger(__name__)

PASSING_TEACHBACK_SCORE = 60
_RESOLVING_RATINGS = frozenset({"good", "easy"})


async def resolve_for_flashcard(session: AsyncSession, flashcard_id: str) -> int:
    result = await session.execute(
        update(MisconceptionModel)
        .where(MisconceptionModel.flashcard_id == flashcard_id)
        .where(MisconceptionModel.status == "open")
        .values(status="resolved", resolved_at=datetime.now(UTC))
    )
    resolved = result.rowcount or 0
    if resolved:
        logger.info(
            "Resolved misconceptions",
            extra={"flashcard_id": flashcard_id, "count": resolved},
        )
    return resolved


async def resolve_on_review(session: AsyncSession, flashcard_id: str, rating: str) -> int:
    if rating not in _RESOLVING_RATINGS:
        return 0
    return await resolve_for_flashcard(session, flashcard_id)


async def _count(session: AsyncSession, *conditions) -> int:
    result = await session.execute(
        select(func.count()).select_from(MisconceptionModel).where(*conditions)
    )
    return int(result.scalar_one())


async def get_stats(session: AsyncSession) -> dict:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    return {
        "open_count": await _count(session, MisconceptionModel.status == "open"),
        "resolved_count": await _count(session, MisconceptionModel.status == "resolved"),
        "resolved_last_30d": await _count(
            session,
            MisconceptionModel.status == "resolved",
            MisconceptionModel.resolved_at >= cutoff,
        ),
    }
