"""Reads and writes for quizzes, their bank of items and the learner's attempts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkModel,
    FlashcardModel,
    QuizAttemptModel,
    QuizItemModel,
    QuizModel,
    QuizOptionModel,
    QuizQuestionModel,
    SectionModel,
)
from app.repos._helpers import get_or_404
from app.types import CARD_ARCHIVED


class QuizRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_404(self, quiz_id: str) -> QuizModel:
        return await get_or_404(self.session, QuizModel, quiz_id, name="Quiz")

    async def item_or_404(self, item_id: str) -> QuizItemModel:
        return await get_or_404(self.session, QuizItemModel, item_id, name="Quiz item")

    async def questions(self, quiz_id: str) -> list[QuizQuestionModel]:
        result = await self.session.execute(
            select(QuizQuestionModel)
            .where(QuizQuestionModel.quiz_id == quiz_id)
            .order_by(QuizQuestionModel.position)
        )
        return list(result.scalars().all())

    async def items(self, item_ids: Collection[str]) -> dict[str, QuizItemModel]:
        if not item_ids:
            return {}
        result = await self.session.execute(
            select(QuizItemModel).where(QuizItemModel.id.in_(list(item_ids)))
        )
        return {i.id: i for i in result.scalars().all()}

    async def options_by_item(self, item_ids: Collection[str]) -> dict[str, list[QuizOptionModel]]:
        out: dict[str, list[QuizOptionModel]] = defaultdict(list)
        if not item_ids:
            return out
        result = await self.session.execute(
            select(QuizOptionModel)
            .where(QuizOptionModel.item_id.in_(list(item_ids)))
            .order_by(QuizOptionModel.item_id, QuizOptionModel.position)
        )
        for option in result.scalars().all():
            out[option.item_id].append(option)
        return out

    async def attempts(self, quiz_id: str) -> dict[int, QuizAttemptModel]:
        result = await self.session.execute(
            select(QuizAttemptModel).where(QuizAttemptModel.quiz_id == quiz_id)
        )
        return {a.position: a for a in result.scalars().all()}

    async def unseen_items(
        self,
        document_id: str,
        section_ids: Collection[str] | None,
        level: str,
        kind: str,
        exclude: Collection[str],
        limit: int,
    ) -> list[QuizItemModel]:
        """Banked items at *level* and *kind* that nobody has answered yet, oldest first."""
        answered = select(QuizAttemptModel.item_id).distinct()
        stmt = select(QuizItemModel).where(
            QuizItemModel.document_id == document_id,
            QuizItemModel.difficulty == level,
            QuizItemModel.kind == kind,
            QuizItemModel.support_check != "unsupported",
            QuizItemModel.id.not_in(answered),
        )
        if section_ids is not None:
            stmt = stmt.where(QuizItemModel.section_id.in_(list(section_ids)))
        if exclude:
            stmt = stmt.where(QuizItemModel.id.not_in(list(exclude)))
        result = await self.session.execute(stmt.order_by(QuizItemModel.created_at).limit(limit))
        return list(result.scalars().all())

    async def used_chunk_ids(self, document_id: str) -> set[str]:
        """Chunks some banked item of this document was written from."""
        result = await self.session.execute(
            select(QuizItemModel.source_chunk_ids).where(QuizItemModel.document_id == document_id)
        )
        return {cid for ids in result.scalars().all() for cid in (ids or [])}

    async def missed_by_section(self, document_id: str) -> dict[str, int]:
        """Answers that were not fully right, per section, across every quiz on the document."""
        result = await self.session.execute(
            select(QuizItemModel.section_id, func.count())
            .join(QuizAttemptModel, QuizAttemptModel.item_id == QuizItemModel.id)
            .where(QuizItemModel.document_id == document_id, QuizAttemptModel.outcome != "correct")
            .group_by(QuizItemModel.section_id)
        )
        return {sid: n for sid, n in result.all() if sid}

    async def lapses_by_section(self, document_id: str) -> dict[str, int]:
        """Card lapses per section, through the chunk each card is filed under."""
        result = await self.session.execute(
            select(ChunkModel.section_id, func.sum(FlashcardModel.lapses))
            .join(ChunkModel, ChunkModel.id == FlashcardModel.chunk_id)
            .where(FlashcardModel.document_id == document_id)
            .group_by(ChunkModel.section_id)
        )
        return {sid: int(n or 0) for sid, n in result.all() if sid}

    async def grounded_cards(
        self, document_id: str, section_ids: Collection[str] | None = None
    ) -> list[tuple[FlashcardModel, str | None]]:
        """Live cards whose quote was checked against their passage, with their section."""
        stmt = (
            select(FlashcardModel, ChunkModel.section_id)
            .outerjoin(ChunkModel, ChunkModel.id == FlashcardModel.chunk_id)
            .where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.grounding == "verified",
                FlashcardModel.fsrs_state != CARD_ARCHIVED,
            )
        )
        if section_ids is not None:
            stmt = stmt.where(ChunkModel.section_id.in_(list(section_ids)))
        result = await self.session.execute(stmt)
        return [(card, sid) for card, sid in result.all()]

    async def section_headings(self, section_ids: Collection[str]) -> dict[str, str]:
        if not section_ids:
            return {}
        result = await self.session.execute(
            select(SectionModel.id, SectionModel.heading).where(
                SectionModel.id.in_(list(section_ids))
            )
        )
        return dict(result.all())

    async def chunks(self, chunk_ids: Sequence[str]) -> list[ChunkModel]:
        if not chunk_ids:
            return []
        result = await self.session.execute(
            select(ChunkModel).where(ChunkModel.id.in_(list(chunk_ids)))
        )
        by_id = {c.id: c for c in result.scalars().all()}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    def add_all(self, rows: Sequence[object]) -> None:
        self.session.add_all(rows)
