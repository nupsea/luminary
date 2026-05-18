"""Repository for `DocumentModel` reads and writes.

Owns simple `session.execute / commit` calls for the documents router.
The cascading delete (18 child tables, LanceDB + Kuzu + filesystem
side-effects) and the heavily denormalized `list_documents` query (10+
correlated scalar subqueries) stay inline -- both are bespoke
orchestrations, not reusable repo methods.

Many documents endpoints use `async with get_session_factory()() as
session:` rather than `Depends(get_db)`. `DocumentRepo(session)` works
inside those blocks; `get_document_repo` is provided for endpoints that
already use `Depends(get_db)`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ChunkModel,
    DocumentModel,
    ReadingProgressModel,
    SectionModel,
)
from app.services.repo_helpers import get_or_404


class DocumentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def get_or_404(self, document_id: str) -> DocumentModel:
        return await get_or_404(self.session, DocumentModel, document_id, name="Document")

    async def find_by_file_hash(self, file_hash: str) -> DocumentModel | None:
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    # -- list reads --------------------------------------------------------

    async def sections_for_document(self, document_id: str) -> Sequence[SectionModel]:
        result = await self.session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        return result.scalars().all()

    async def chunks_for_document(
        self,
        document_id: str,
        *,
        by_section: bool = False,
    ) -> Sequence[ChunkModel]:
        stmt = select(ChunkModel).where(ChunkModel.document_id == document_id)
        if by_section:
            stmt = stmt.order_by(ChunkModel.section_id, ChunkModel.chunk_index)
        else:
            stmt = stmt.order_by(ChunkModel.chunk_index)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def chunk_counts_by_section(self, document_id: str) -> dict[str, int]:
        """Return {section_id: chunk_count} for a document. Skips chunks
        with null section_id (orphan / unmapped)."""
        result = await self.session.execute(
            select(ChunkModel.section_id, func.count(ChunkModel.id))
            .where(
                ChunkModel.document_id == document_id,
                ChunkModel.section_id.isnot(None),
            )
            .group_by(ChunkModel.section_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def read_section_count(self, document_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).where(ReadingProgressModel.document_id == document_id)
        )
        return result.scalar_one() or 0

    async def upsert_reading_progress(
        self, *, document_id: str, section_id: str
    ) -> ReadingProgressModel:
        """Increment view_count on repeat visits; create a new row otherwise.
        Caller must have already verified the document exists."""
        now = datetime.now(UTC)
        existing = (
            await self.session.execute(
                select(ReadingProgressModel).where(
                    ReadingProgressModel.document_id == document_id,
                    ReadingProgressModel.section_id == section_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            row = ReadingProgressModel(
                id=str(uuid.uuid4()),
                document_id=document_id,
                section_id=section_id,
                first_seen_at=now,
                last_seen_at=now,
                view_count=1,
            )
            self.session.add(row)
            await self.session.commit()
            await self.session.refresh(row)
            return row
        existing.last_seen_at = now
        existing.view_count += 1
        await self.session.commit()
        await self.session.refresh(existing)
        return existing

    # -- writes ------------------------------------------------------------

    async def commit(self) -> None:
        await self.session.commit()


def get_document_repo(session: AsyncSession = Depends(get_db)) -> DocumentRepo:
    return DocumentRepo(session)
