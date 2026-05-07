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

from collections.abc import Sequence

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

    async def chunks_for_document(self, document_id: str) -> Sequence[ChunkModel]:
        result = await self.session.execute(
            select(ChunkModel)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.chunk_index)
        )
        return result.scalars().all()

    async def read_section_count(self, document_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).where(ReadingProgressModel.document_id == document_id)
        )
        return result.scalar_one() or 0

    # -- writes ------------------------------------------------------------

    async def commit(self) -> None:
        await self.session.commit()


def get_document_repo(session: AsyncSession = Depends(get_db)) -> DocumentRepo:
    return DocumentRepo(session)
