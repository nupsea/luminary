"""What a library holds, counted, so a moved library can be checked against its original."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentModel, FlashcardModel, NoteModel


class LibraryContentsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def counts(self) -> dict[str, int]:
        out = {}
        for name, model in (
            ("documents", DocumentModel),
            ("flashcards", FlashcardModel),
            ("notes", NoteModel),
        ):
            out[name] = (await self.session.scalar(select(func.count()).select_from(model))) or 0
        return out
