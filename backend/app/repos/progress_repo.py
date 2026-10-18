"""Counts behind the Progress page.

Cutoffs are tz-naive UTC: aiosqlite hands DateTime columns back naive (docs/patterns.md).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocumentModel,
    FlashcardModel,
    NoteModel,
    ReviewEventModel,
    TimeOnTaskModel,
)
from app.repos._helpers import local_date, local_month


class ProgressRepo:
    def __init__(self, session: AsyncSession, tz_offset_minutes: int = 0) -> None:
        self.session = session
        self._tz_offset_minutes = tz_offset_minutes

    async def _count(self, stmt) -> int:
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # -- reviews -----------------------------------------------------------

    async def review_totals_since(self, cutoff: datetime) -> tuple[int, int]:
        """(reviews, correct reviews) since `cutoff`."""
        row = (
            await self.session.execute(
                select(
                    func.count(ReviewEventModel.id),
                    func.sum(func.cast(ReviewEventModel.is_correct, Integer)),
                ).where(ReviewEventModel.reviewed_at >= cutoff)
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    async def count_reviews_since(self, cutoff: datetime) -> int:
        return await self._count(
            select(func.count())
            .select_from(ReviewEventModel)
            .where(ReviewEventModel.reviewed_at >= cutoff)
        )

    async def active_days_since(self, cutoff: datetime) -> set[str]:
        """Local dates carrying a graded review or a recorded time-on-task interval."""
        review_days = await self.session.execute(
            select(local_date(ReviewEventModel.reviewed_at, self._tz_offset_minutes)).where(
                ReviewEventModel.reviewed_at >= cutoff
            )
        )
        task_days = await self.session.execute(
            select(local_date(TimeOnTaskModel.started_at, self._tz_offset_minutes)).where(
                TimeOnTaskModel.started_at >= cutoff
            )
        )
        return {d for (d,) in review_days if d} | {d for (d,) in task_days if d}

    # -- cards -------------------------------------------------------------

    async def reviewed_cards(self) -> list[FlashcardModel]:
        result = await self.session.execute(select(FlashcardModel).where(FlashcardModel.reps > 0))
        return list(result.scalars().all())

    async def count_reviewed_cards(self) -> int:
        return await self._count(
            select(func.count()).select_from(FlashcardModel).where(FlashcardModel.reps > 0)
        )

    async def count_mature_cards(self, min_stability_days: float) -> int:
        return await self._count(
            select(func.count())
            .select_from(FlashcardModel)
            .where(
                FlashcardModel.fsrs_state == "review",
                FlashcardModel.fsrs_stability >= min_stability_days,
            )
        )

    async def count_cards_due_by(self, now: datetime) -> int:
        return await self._count(
            select(func.count()).select_from(FlashcardModel).where(FlashcardModel.due_date <= now)
        )

    async def count_cards(self) -> int:
        return await self._count(select(func.count()).select_from(FlashcardModel))

    # -- library -----------------------------------------------------------

    async def count_documents(self) -> int:
        return await self._count(select(func.count()).select_from(DocumentModel))

    async def count_live_notes(self) -> int:
        return await self._count(
            select(func.count()).select_from(NoteModel).where(NoteModel.archived.is_(False))
        )

    async def live_notes_per_month(self) -> list[tuple[str, int]]:
        """(local YYYY-MM, notes), oldest first, archived notes excluded."""
        month = local_month(NoteModel.created_at, self._tz_offset_minutes)
        rows = (
            await self.session.execute(
                select(month.label("month"), func.count().label("count"))
                .where(NoteModel.archived.is_(False))
                .group_by(month)
                .order_by(month)
            )
        ).all()
        return [(str(r.month), int(r.count)) for r in rows]
