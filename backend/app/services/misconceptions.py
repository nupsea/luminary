import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos.misconception_repo import MisconceptionRepo

logger = logging.getLogger(__name__)

PASSING_TEACHBACK_SCORE = 60
_RESOLVING_RATINGS = frozenset({"good", "easy"})


async def resolve_for_flashcard(session: AsyncSession, flashcard_id: str) -> int:
    resolved = await MisconceptionRepo(session).resolve_open(flashcard_id, datetime.now(UTC))
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


async def get_stats(session: AsyncSession) -> dict:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    repo = MisconceptionRepo(session)
    return {
        "open_count": await repo.count("open"),
        "resolved_count": await repo.count("resolved"),
        "resolved_last_30d": await repo.count("resolved", resolved_since=cutoff),
    }
