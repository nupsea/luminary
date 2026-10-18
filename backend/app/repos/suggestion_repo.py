"""Suggested questions shown to the learner, and whether they were asked."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSuggestionHistoryModel


class SuggestionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def unasked(self, document_id: str | None, limit: int) -> list[tuple[str, str]]:
        """(id, text) of the latest suggestions not yet asked; a null id is the all-scope."""
        result = await self.session.execute(
            select(ChatSuggestionHistoryModel.id, ChatSuggestionHistoryModel.suggestion_text)
            .where(
                ChatSuggestionHistoryModel.was_asked.is_(False),
                ChatSuggestionHistoryModel.document_id == document_id,
            )
            .order_by(ChatSuggestionHistoryModel.shown_at.desc())
            .limit(limit)
        )
        return [(i, text) for i, text in result.all()]

    async def count_asked(self, document_id: str | None) -> int:
        """Suggestions the learner asked; a null id is the all-scope."""
        result = await self.session.execute(
            select(func.count())
            .select_from(ChatSuggestionHistoryModel)
            .where(
                ChatSuggestionHistoryModel.was_asked.is_(True),
                ChatSuggestionHistoryModel.document_id.is_(None)
                if document_id is None
                else ChatSuggestionHistoryModel.document_id == document_id,
            )
        )
        return int(result.scalar() or 0)

    async def recent_texts(self, document_id: str | None, limit: int) -> list[str]:
        result = await self.session.execute(
            select(ChatSuggestionHistoryModel.suggestion_text)
            .where(ChatSuggestionHistoryModel.document_id == document_id)
            .order_by(ChatSuggestionHistoryModel.shown_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_asked(self, suggestion_id: str) -> bool:
        result = await self.session.execute(
            update(ChatSuggestionHistoryModel)
            .where(ChatSuggestionHistoryModel.id == suggestion_id)
            .values(was_asked=True)
        )
        return result.rowcount > 0
