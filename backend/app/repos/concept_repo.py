"""Reads over `concepts` rows for the concepts router."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConceptModel, FlashcardModel


class ConceptRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def id_labels(self) -> list[tuple[str, str]]:
        result = await self.session.execute(select(ConceptModel.id, ConceptModel.label))
        return [(cid, label) for cid, label in result.all()]

    async def listed(self, status: str | None = None) -> Sequence[ConceptModel]:
        """Weakest first, optionally of one status."""
        stmt = select(ConceptModel)
        if status:
            stmt = stmt.where(ConceptModel.status == status)
        result = await self.session.execute(stmt.order_by(ConceptModel.mastery.asc()))
        return result.scalars().all()

    async def first(self, limit: int) -> Sequence[ConceptModel]:
        result = await self.session.execute(select(ConceptModel).limit(limit))
        return result.scalars().all()

    async def weakest_tracked(self, limit: int) -> list[str]:
        """Ids of non-candidate concepts, never-reviewed first, then lowest mastery."""
        result = await self.session.execute(
            select(ConceptModel.id)
            .where(ConceptModel.status != "candidate")
            .order_by(ConceptModel.last_reviewed.is_(None).desc(), ConceptModel.mastery.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def by_ids(self, concept_ids: Collection[str]) -> Sequence[ConceptModel]:
        result = await self.session.execute(
            select(ConceptModel).where(ConceptModel.id.in_(concept_ids))
        )
        return result.scalars().all()

    async def ids_on_note_cards(self, note_id: str) -> set[str]:
        """Concepts the note's own cards point at."""
        result = await self.session.execute(
            select(FlashcardModel.concept_id).where(
                FlashcardModel.note_id == note_id, FlashcardModel.concept_id.is_not(None)
            )
        )
        return {cid for cid in result.scalars() if cid}
