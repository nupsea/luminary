"""Reads that analyse a deck: cards per section, their stability and Bloom levels, and the
cards still waiting on a factuality check."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel, SectionModel


class DeckStatsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _judgeable(self, factuality: str, document_id: str | None):  # noqa: ANN202 -- a Select
        stmt = select(FlashcardModel).where(
            FlashcardModel.factuality == factuality,
            FlashcardModel.source_chunk_ids.isnot(None),
        )
        if document_id is not None:
            stmt = stmt.where(FlashcardModel.document_id == document_id)
        return stmt

    async def judgeable(
        self, factuality: str, document_id: str | None, limit: int
    ) -> list[FlashcardModel]:
        """Cards in this factuality state that recorded the passage they were written from."""
        result = await self.session.execute(self._judgeable(factuality, document_id).limit(limit))
        return list(result.scalars().all())

    async def count_judgeable(self, factuality: str, document_id: str | None) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(self._judgeable(factuality, document_id).subquery())
        )
        return int(result.scalar_one())

    async def avg_stability_by_section(self, document_id: str) -> dict[str, float]:
        """{section id: mean FSRS stability} over the document's non-definition cards."""
        result = await self.session.execute(
            select(ChunkModel.section_id, func.avg(FlashcardModel.fsrs_stability))
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.fsrs_stability.is_not(None),
                or_(
                    FlashcardModel.flashcard_type.is_(None),
                    FlashcardModel.flashcard_type != "definition",
                ),
                ChunkModel.section_id.is_not(None),
            )
            .group_by(ChunkModel.section_id)
        )
        return {sid: float(avg) for sid, avg in result.all() if avg is not None}

    async def with_section_ids(
        self,
        *,
        card_ids: Sequence[str] | None = None,
        document_id: str | None = None,
        exclude_archived: bool = False,
    ) -> list[tuple[FlashcardModel, str | None]]:
        """(card, its chunk's section id); None when the card has no chunk or it is gone."""
        stmt = select(FlashcardModel, ChunkModel.section_id).outerjoin(
            ChunkModel, FlashcardModel.chunk_id == ChunkModel.id
        )
        if card_ids is not None:
            stmt = stmt.where(FlashcardModel.id.in_(list(card_ids)))
        if document_id is not None:
            stmt = stmt.where(FlashcardModel.document_id == document_id)
        if exclude_archived:
            stmt = stmt.where(FlashcardModel.fsrs_state != "archived")
        return [(card, sid) for card, sid in (await self.session.execute(stmt)).all()]

    async def live_with_stability_over(
        self, document_id: str, stability_days: float
    ) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel).where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.fsrs_stability > stability_days,
                FlashcardModel.fsrs_state != "archived",
            )
        )
        return list(result.scalars().all())

    async def bloom_by_section(self, document_id: str) -> list[tuple[int, str, str]]:
        """(bloom level, section id, heading) per card anchored in a section of the document."""
        result = await self.session.execute(
            select(FlashcardModel.bloom_level, ChunkModel.section_id, SectionModel.heading)
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .join(SectionModel, ChunkModel.section_id == SectionModel.id)
            .where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.bloom_level.is_not(None),
            )
        )
        return [(int(level), sid, heading) for level, sid, heading in result.all()]
