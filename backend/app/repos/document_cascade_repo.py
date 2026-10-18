"""SQLite deletes behind removing or re-parsing a document. Nothing here commits."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChatSessionModel,
    CollectionMemberModel,
    LibrarySummaryModel,
)


class DocumentCascadeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def delete_keyed_rows(self, document_id: str, models: Iterable[type]) -> dict[str, int]:
        """Delete each model's rows for the document; {table name: rows deleted}."""
        counts: dict[str, int] = {}
        for model in models:
            result = await self.session.execute(
                delete(model).where(model.document_id == document_id)  # type: ignore[attr-defined]
            )
            counts[model.__tablename__] = result.rowcount or 0  # type: ignore[attr-defined]
        return counts

    async def count_keyed_rows(self, document_id: str, model: type) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(model).where(model.document_id == document_id)  # type: ignore[attr-defined]
        )
        return int(result.scalar_one() or 0)

    async def delete_fts_rows(self, document_id: str) -> None:
        # FTS shadow tables are not reached by an ORM delete.
        for table in ("chunks_fts", "images_fts"):
            await self.session.execute(
                text(f"DELETE FROM {table} WHERE document_id = :doc_id"),  # noqa: S608 -- fixed names
                {"doc_id": document_id},
            )

    async def chats_mentioning(self, document_id: str) -> list[ChatSessionModel]:
        """Chat sessions whose JSON scope may name the document; callers re-check the list."""
        result = await self.session.execute(
            select(ChatSessionModel).where(ChatSessionModel.document_ids.like(f"%{document_id}%"))
        )
        return list(result.scalars().all())

    async def delete_collection_membership(self, document_id: str) -> None:
        await self.session.execute(
            delete(CollectionMemberModel).where(
                CollectionMemberModel.member_id == document_id,
                CollectionMemberModel.member_type == "document",
            )
        )

    async def delete_library_summary(self) -> None:
        await self.session.execute(delete(LibrarySummaryModel))
