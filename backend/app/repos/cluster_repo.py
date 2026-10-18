"""Note-cluster suggestions: the collections HDBSCAN proposes and the user accepts or rejects."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClusterSuggestionModel


class ClusterRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(self, suggestion_id: str) -> ClusterSuggestionModel | None:
        result = await self.session.execute(
            select(ClusterSuggestionModel).where(ClusterSuggestionModel.id == suggestion_id)
        )
        return result.scalar_one_or_none()

    async def has_pending_since(self, cutoff: datetime) -> bool:
        result = await self.session.execute(
            select(ClusterSuggestionModel)
            .where(ClusterSuggestionModel.status == "pending")
            .where(ClusterSuggestionModel.created_at > cutoff)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def latest_pending_at(self) -> datetime | None:
        result = await self.session.execute(
            select(ClusterSuggestionModel.created_at)
            .where(ClusterSuggestionModel.status == "pending")
            .order_by(ClusterSuggestionModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def pending_by_confidence(self) -> list[ClusterSuggestionModel]:
        result = await self.session.execute(
            select(ClusterSuggestionModel)
            .where(ClusterSuggestionModel.status == "pending")
            .order_by(ClusterSuggestionModel.confidence_score.desc())
        )
        return list(result.scalars().all())

    async def pending_among(
        self, suggestion_ids: Sequence[str]
    ) -> dict[str, ClusterSuggestionModel]:
        result = await self.session.execute(
            select(ClusterSuggestionModel).where(
                ClusterSuggestionModel.id.in_(list(suggestion_ids)),
                ClusterSuggestionModel.status == "pending",
            )
        )
        return {s.id: s for s in result.scalars().all()}
