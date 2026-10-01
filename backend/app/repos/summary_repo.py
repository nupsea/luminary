"""Stored document and library summaries, and the rows summaries are built from."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, delete, exists, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkModel,
    DocumentModel,
    LibrarySummaryModel,
    SectionSummaryModel,
    SummaryModel,
)

# Which stored summary describes a document best in the library synthesis.
_MODE_PRIORITY = {"executive": 0, "detailed": 1, "one_sentence": 2, "conversation": 3}


class SummaryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def facets(self, document_id: str):  # noqa: ANN201 -- a Row of (form, domain, register)
        return (
            await self.session.execute(
                select(DocumentModel.form, DocumentModel.domain, DocumentModel.register).where(
                    DocumentModel.id == document_id
                )
            )
        ).first()

    async def chunks(self, document_id: str) -> list[ChunkModel]:
        result = await self.session.execute(
            select(ChunkModel)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.chunk_index)
        )
        return list(result.scalars().all())

    async def section_summaries(self, document_id: str) -> list[SectionSummaryModel]:
        result = await self.session.execute(
            select(SectionSummaryModel)
            .where(SectionSummaryModel.document_id == document_id)
            .order_by(SectionSummaryModel.unit_index)
        )
        return list(result.scalars().all())

    async def latest(self, document_id: str, mode: str) -> SummaryModel | None:
        result = await self.session.execute(
            select(SummaryModel)
            .where(SummaryModel.document_id == document_id)
            .where(SummaryModel.mode == mode)
            .order_by(SummaryModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def insert_if_document_exists(
        self, document_id: str, mode: str, content: str
    ) -> str | None:
        """Insert in the same statement that checks the document still exists: a
        separate check could pass just before a delete commits. None when skipped."""
        summary_id = str(uuid.uuid4())
        row = select(
            literal(summary_id),
            literal(document_id),
            literal(mode),
            literal(content),
            literal(datetime.now(UTC), DateTime),
        ).where(exists().where(DocumentModel.id == document_id))
        result = await self.session.execute(
            insert(SummaryModel).from_select(
                ["id", "document_id", "mode", "content", "created_at"], row
            )
        )
        return summary_id if result.rowcount else None

    async def delete_mode(self, document_id: str, mode: str) -> None:
        await self.session.execute(
            delete(SummaryModel)
            .where(SummaryModel.document_id == document_id)
            .where(SummaryModel.mode == mode)
        )

    async def latest_library(self, mode: str) -> LibrarySummaryModel | None:
        result = await self.session.execute(
            select(LibrarySummaryModel)
            .where(LibrarySummaryModel.mode == mode)
            .order_by(LibrarySummaryModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def insert_library_if_sources_exist(
        self, mode: str, content: str, source_ids: list[str]
    ) -> str | None:
        """Insert only if every source document still exists, in one statement.
        None when skipped."""
        summary_id = str(uuid.uuid4())
        wanted = set(source_ids)
        live = (
            select(func.count())
            .select_from(DocumentModel)
            .where(DocumentModel.id.in_(wanted))
            .scalar_subquery()
        )
        row = select(
            literal(summary_id),
            literal(mode),
            literal(content),
            literal(datetime.now(UTC), DateTime),
        ).where(live == len(wanted))
        result = await self.session.execute(
            insert(LibrarySummaryModel).from_select(["id", "mode", "content", "created_at"], row)
        )
        return summary_id if result.rowcount else None

    async def best_document_summaries(self) -> dict[str, str]:
        """The best stored summary of each live document: executive, then detailed,
        one_sentence, conversation. Documents with none are absent."""
        rows = await self.session.execute(
            select(SummaryModel.document_id, SummaryModel.mode, SummaryModel.content)
            # A summary that outlived its document must not describe the library.
            .join(DocumentModel, DocumentModel.id == SummaryModel.document_id)
            .order_by(SummaryModel.created_at.desc())
        )
        best: dict[str, tuple[int, str]] = {}
        for row in rows:
            prio = _MODE_PRIORITY.get(row.mode, 99)
            if row.document_id not in best or prio < best[row.document_id][0]:
                best[row.document_id] = (prio, row.content)
        return {doc_id: content for doc_id, (_, content) in best.items()}

    async def titles(self, document_ids: list[str]) -> dict[str, str]:
        rows = await self.session.execute(
            select(DocumentModel.id, DocumentModel.title).where(DocumentModel.id.in_(document_ids))
        )
        return {row.id: row.title for row in rows}
