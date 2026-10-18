"""Reads behind concept mastery: chunks naming a concept, their cards, and wrong predictions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, ConceptModel, FlashcardModel, PredictionEventModel


class MasteryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def chunk_ids_mentioning(self, name: str, document_ids: Sequence[str]) -> list[str]:
        """Chunks of these documents whose text contains `name`, case-insensitively."""
        result = await self.session.execute(
            select(ChunkModel.id).where(
                ChunkModel.document_id.in_(list(document_ids)),
                func.lower(ChunkModel.text).like(f"%{name.lower()}%"),
            )
        )
        return list(result.scalars().all())

    async def cards_on_chunks(self, chunk_ids: Sequence[str]) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel).where(FlashcardModel.chunk_id.in_(list(chunk_ids)))
        )
        return list(result.scalars().all())

    async def wrong_predictions(self, chunk_ids: Sequence[str]) -> int:
        result = await self.session.execute(
            select(func.count()).where(
                PredictionEventModel.chunk_id.in_(list(chunk_ids)),
                PredictionEventModel.correct.is_(False),
            )
        )
        return result.scalar_one() or 0

    async def cards_due_by(self, chunk_ids: Sequence[str], cutoff: datetime) -> int:
        result = await self.session.execute(
            select(func.count()).where(
                FlashcardModel.chunk_id.in_(list(chunk_ids)),
                FlashcardModel.due_date <= cutoff,
            )
        )
        return result.scalar_one() or 0

    async def concept(self, concept_id: str) -> ConceptModel | None:
        return await self.session.get(ConceptModel, concept_id)

    # -- heatmap: three grouped reads over a document's chosen sections -----

    def _section_chunk_ids(self, document_id: str, section_ids: Sequence[str]):
        # A subquery, not a bound list: a long document can hold more chunks than
        # SQLite allows bound variables in one statement.
        return (
            select(ChunkModel.id)
            .where(
                ChunkModel.document_id == document_id,
                ChunkModel.section_id.in_(list(section_ids)),
            )
            .scalar_subquery()
        )

    async def section_chunk_texts(
        self, document_id: str, section_ids: Sequence[str]
    ) -> list[tuple[str, str, str | None]]:
        """(chunk id, section id, text)."""
        result = await self.session.execute(
            select(ChunkModel.id, ChunkModel.section_id, ChunkModel.text).where(
                ChunkModel.document_id == document_id,
                ChunkModel.section_id.in_(list(section_ids)),
            )
        )
        return [(c, s, t) for c, s, t in result.all()]

    async def section_cards(
        self, document_id: str, section_ids: Sequence[str]
    ) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel).where(
                FlashcardModel.chunk_id.in_(self._section_chunk_ids(document_id, section_ids))
            )
        )
        return list(result.scalars().all())

    async def section_wrong_predictions(
        self, document_id: str, section_ids: Sequence[str]
    ) -> dict[str, int]:
        """{chunk id: wrong predictions}; chunks with none are absent."""
        result = await self.session.execute(
            select(PredictionEventModel.chunk_id, func.count())
            .where(
                PredictionEventModel.chunk_id.in_(
                    self._section_chunk_ids(document_id, section_ids)
                ),
                PredictionEventModel.correct.is_(False),
            )
            .group_by(PredictionEventModel.chunk_id)
        )
        return {cid: int(n) for cid, n in result.all()}
