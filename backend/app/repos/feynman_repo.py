"""Feynman sessions and their tutor/learner turns."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FeynmanSessionModel, FeynmanTurnModel


class FeynmanRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(self, session_id: str) -> FeynmanSessionModel | None:
        return await self.session.get(FeynmanSessionModel, session_id)

    async def turns(self, session_id: str) -> list[FeynmanTurnModel]:
        result = await self.session.execute(
            select(FeynmanTurnModel)
            .where(FeynmanTurnModel.session_id == session_id)
            .order_by(FeynmanTurnModel.turn_index)
        )
        return list(result.scalars().all())

    async def list_for_document(self, document_id: str) -> list[FeynmanSessionModel]:
        result = await self.session.execute(
            select(FeynmanSessionModel)
            .where(FeynmanSessionModel.document_id == document_id)
            .order_by(FeynmanSessionModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def tutor_turns(self, session_ids: Sequence[str]) -> list[FeynmanTurnModel]:
        result = await self.session.execute(
            select(FeynmanTurnModel).where(
                FeynmanTurnModel.session_id.in_(list(session_ids)),
                FeynmanTurnModel.role == "tutor",
            )
        )
        return list(result.scalars().all())
