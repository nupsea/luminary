"""Suggested questions shown to the learner, and whether they were asked."""

from __future__ import annotations

from sqlalchemy import select
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
