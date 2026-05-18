"""Repository for `FlashcardModel` reads and writes.

Owns simple `session.execute / commit / delete` calls for the flashcards
router. Endpoints that interleave FTS sync mid-transaction
(`create_trace_flashcard`, `update_flashcard`) keep the FTS calls inline
because the ordering matters and FTS is a router-layer concern handled
through `app.services.flashcard` helpers. The deck aggregation in
`list_flashcard_decks` and the cross-entity joins in `get_source_context`
also stay inline.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ChunkModel, FlashcardModel
from app.services.repo_helpers import get_or_404


class FlashcardRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def get_or_404(self, card_id: str) -> FlashcardModel:
        return await get_or_404(self.session, FlashcardModel, card_id, name="Flashcard")

    # -- list reads --------------------------------------------------------

    async def list_for_document(
        self,
        document_id: str,
        *,
        bloom_level_min: int | None = None,
    ) -> Sequence[FlashcardModel]:
        stmt = select(FlashcardModel).where(FlashcardModel.document_id == document_id)
        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )
        stmt = stmt.order_by(FlashcardModel.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_section(
        self,
        document_id: str,
        section_id: str,
        *,
        bloom_level_min: int | None = None,
    ) -> list[tuple[FlashcardModel, str]]:
        """Return (card, section_id) pairs joined through ChunkModel."""
        stmt = (
            select(FlashcardModel, ChunkModel.section_id)
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .where(
                FlashcardModel.document_id == document_id,
                ChunkModel.section_id == section_id,
            )
        )
        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )
        stmt = stmt.order_by(FlashcardModel.created_at.desc())
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_existing_ids_in(self, card_ids: Sequence[str]) -> list[str]:
        if not card_ids:
            return []
        result = await self.session.execute(
            select(FlashcardModel.id).where(FlashcardModel.id.in_(list(card_ids)))
        )
        return list(result.scalars().all())

    async def list_ids_for_document(self, document_id: str) -> list[str]:
        result = await self.session.execute(
            select(FlashcardModel.id).where(FlashcardModel.document_id == document_id)
        )
        return list(result.scalars().all())

    # -- writes ------------------------------------------------------------

    async def commit_refresh(self, card: FlashcardModel) -> FlashcardModel:
        await self.session.commit()
        await self.session.refresh(card)
        return card

    async def delete_by_id(self, card_id: str) -> None:
        await self.session.execute(delete(FlashcardModel).where(FlashcardModel.id == card_id))
        await self.session.commit()

    async def delete_by_ids(self, card_ids: Sequence[str]) -> None:
        if not card_ids:
            await self.session.commit()
            return
        await self.session.execute(
            delete(FlashcardModel).where(FlashcardModel.id.in_(list(card_ids)))
        )
        await self.session.commit()

    async def delete_for_document(self, document_id: str) -> None:
        await self.session.execute(
            delete(FlashcardModel).where(FlashcardModel.document_id == document_id)
        )
        await self.session.commit()


def get_flashcard_repo(session: AsyncSession = Depends(get_db)) -> FlashcardRepo:
    return FlashcardRepo(session)
