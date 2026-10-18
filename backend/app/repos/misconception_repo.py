"""Misconceptions a learner showed, open until a later answer resolves them. Nothing commits."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MisconceptionModel


class MisconceptionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_open(self, flashcard_id: str, at: datetime) -> int:
        """Mark the card's open misconceptions resolved; how many were."""
        result = await self.session.execute(
            update(MisconceptionModel)
            .where(
                MisconceptionModel.flashcard_id == flashcard_id,
                MisconceptionModel.status == "open",
            )
            .values(status="resolved", resolved_at=at)
        )
        return result.rowcount or 0

    async def count(self, status: str, *, resolved_since: datetime | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(MisconceptionModel)
            .where(MisconceptionModel.status == status)
        )
        if resolved_since is not None:
            stmt = stmt.where(MisconceptionModel.resolved_at >= resolved_since)
        return int((await self.session.execute(stmt)).scalar_one())
