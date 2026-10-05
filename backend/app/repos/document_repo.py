"""Repository for `DocumentModel` reads and writes.

Owns simple `session.execute / commit` calls for the documents router.
The cascading delete (18 child tables, LanceDB + filesystem
side-effects) and the heavily denormalized `list_documents` query (10+
correlated scalar subqueries) stay inline -- both are bespoke
orchestrations, not reusable repo methods.

Many documents endpoints use `async with get_session_factory()() as
session:` rather than `Depends(get_db)`. `DocumentRepo(session)` works
inside those blocks; `get_document_repo` is provided for endpoints that
already use `Depends(get_db)`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import NamedTuple

from fastapi import Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_session_factory
from app.models import (
    ChunkModel,
    DocumentModel,
    EnrichmentJobModel,
    ReadingPositionModel,
    ReadingProgressModel,
    SectionModel,
)
from app.repos._helpers import get_or_404

logger = logging.getLogger(__name__)


class DocumentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def get_or_404(self, document_id: str) -> DocumentModel:
        return await get_or_404(self.session, DocumentModel, document_id, name="Document")

    async def corpus_counts(self) -> tuple[int, int]:
        """(documents, chunks) across the whole library.

        The fingerprint an eval run records: retrieval scores what is indexed,
        so two runs taken over different corpora are not comparable.
        """
        documents = await self.session.execute(select(func.count(DocumentModel.id)))
        chunks = await self.session.execute(select(func.count(ChunkModel.id)))
        return int(documents.scalar_one() or 0), int(chunks.scalar_one() or 0)

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

    async def section_extents(self, document_id: str) -> dict[str, tuple[int, int, int, int]]:
        """{section_id: (first chunk_index, characters, first page, last page)} from its chunks.

        Pages come from chunks, not `sections.page_start`: on a PDF whose sections nest, a
        section's own range spans its children's (Hegel: one section claims pages 6-178).
        """
        page = func.nullif(ChunkModel.page_number, 0)
        result = await self.session.execute(
            select(
                ChunkModel.section_id,
                func.min(ChunkModel.chunk_index),
                func.sum(func.length(ChunkModel.text)),
                func.min(page),
                func.max(page),
            )
            .where(ChunkModel.document_id == document_id, ChunkModel.section_id.isnot(None))
            .group_by(ChunkModel.section_id)
        )
        return {
            sid: (int(first), int(chars or 0), int(lo or 0), int(hi or 0))
            for sid, first, chars, lo, hi in result.all()
        }

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

    async def facet_counts(self) -> tuple[dict[str, int], dict[str, int]]:
        """(content_type -> count, format -> count) across the whole library.

        Grouped in SQL because the caller decides which filters to *offer* from
        these numbers: counting a page of documents would hide a filter whose
        matches happen to sit on page two.
        """
        by_type = await self.session.execute(
            select(DocumentModel.content_type, func.count(DocumentModel.id)).group_by(
                DocumentModel.content_type
            )
        )
        by_format = await self.session.execute(
            select(DocumentModel.format, func.count(DocumentModel.id)).group_by(
                DocumentModel.format
            )
        )
        return (
            {row[0]: row[1] for row in by_type.all() if row[0]},
            {row[0]: row[1] for row in by_format.all() if row[0]},
        )

    async def favorite_count(self) -> int:
        result = await self.session.execute(
            select(func.count(DocumentModel.id)).where(DocumentModel.is_favorite.is_(True))
        )
        return result.scalar_one()

    async def chunks_with_headings(
        self, section_ids: Sequence[str]
    ) -> list[tuple[ChunkModel, str]]:
        """(chunk, its section's heading) for these sections, in reading order."""
        result = await self.session.execute(
            select(ChunkModel, SectionModel.heading)
            .join(SectionModel, SectionModel.id == ChunkModel.section_id)
            .where(ChunkModel.section_id.in_(list(section_ids)))
            .order_by(ChunkModel.chunk_index)
        )
        return [(chunk, heading) for chunk, heading in result.all()]

    async def chunks_by_ids(self, chunk_ids: Sequence[str]) -> Sequence[ChunkModel]:
        result = await self.session.execute(
            select(ChunkModel).where(ChunkModel.id.in_(list(chunk_ids)))
        )
        return result.scalars().all()

    async def titles(self, document_ids: Sequence[str]) -> dict[str, str]:
        if not document_ids:
            return {}
        result = await self.session.execute(
            select(DocumentModel.id, DocumentModel.title).where(
                DocumentModel.id.in_(list(document_ids))
            )
        )
        return dict(result.tuples().all())

    async def tags_by_id(
        self, document_ids: Sequence[str] | None = None
    ) -> list[tuple[str, object]]:
        """(id, raw tags) for these documents, or for every document when None."""
        stmt = select(DocumentModel.id, DocumentModel.tags)
        if document_ids is not None:
            stmt = stmt.where(DocumentModel.id.in_(list(document_ids)))
        return [(doc_id, tags) for doc_id, tags in (await self.session.execute(stmt)).all()]

    async def titles_with_chunk_counts(
        self, document_ids: Sequence[str]
    ) -> list[tuple[str, str, int]]:
        """(id, title, chunk count). Chunks, not word_count, which is 0 on many imported books."""
        if not document_ids:
            return []
        chunks = (
            select(func.count(ChunkModel.id))
            .where(ChunkModel.document_id == DocumentModel.id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(DocumentModel.id, DocumentModel.title, chunks).where(
                DocumentModel.id.in_(list(document_ids))
            )
        )
        return [(did, title, int(n or 0)) for did, title, n in result.all()]

    async def list_recently_accessed_complete(self, limit: int) -> Sequence[DocumentModel]:
        result = await self.session.execute(
            select(DocumentModel)
            .where(DocumentModel.stage == "complete")
            .order_by(DocumentModel.last_accessed_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def recently_read(self, since: datetime) -> list[tuple[str, str, str | None]]:
        """(document id, title, last section read) since *since*, most recently read first."""
        result = await self.session.execute(
            select(
                ReadingPositionModel.document_id,
                DocumentModel.title,
                ReadingPositionModel.last_section_id,
            )
            .join(DocumentModel, DocumentModel.id == ReadingPositionModel.document_id)
            .where(ReadingPositionModel.updated_at >= since)
            .order_by(ReadingPositionModel.updated_at.desc())
        )
        return [(doc_id, title, section) for doc_id, title, section in result.all()]

    async def enrichment_in_progress(self, since: datetime) -> bool:
        """Whether any document's enrichment queued or started since *since* is unfinished."""
        result = await self.session.execute(
            select(func.count(EnrichmentJobModel.id)).where(
                EnrichmentJobModel.status.in_(("pending", "running")),
                EnrichmentJobModel.created_at >= since,
            )
        )
        return bool(result.scalar_one())

    async def set_entity_chunks_scanned(self, document_id: str, scanned: int) -> None:
        await self.session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(entity_chunks_scanned=scanned)
        )

    async def set_chapter_prompt_off(self, document_id: str, off: bool) -> None:
        await self.session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(chapter_prompt_off=off)
        )
        await self.session.commit()

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


class ChunkLocation(NamedTuple):
    """Where a chunk sits, in whatever terms its document has.

    Named rather than a bare tuple because it grows: it was a 4-tuple unpacked
    positionally at three call sites, so adding `start_time` to it would have
    silently shifted a field at each one.

    `start_time` is seconds into a recording, null for everything else.
    """

    section_id: str | None
    pdf_page: int | None
    pdf_page_label: str | None
    heading: str | None
    start_time: float | None


async def fetch_chunk_locations(chunk_ids: list[str]) -> dict[str, ChunkLocation]:
    """Where each chunk sits in its document: section, page, and heading.

    A retrieved chunk cannot answer this itself. `embed_node` writes
    `section_heading: ""` and `page: 0` into every vector row, so the fields
    exist in the index and never carry anything, and the keyword path hardcodes
    the same blanks -- the section row is the only place the heading lives and
    `chunks.pdf_page_number` the only place the page does. Both citation paths
    therefore resolve location here rather than trusting the chunk they were
    built from.

    Opens its own session so callers outside a request scope can use it.
    Returns {} on any DB error: a citation without a page is degraded, a failed
    answer is not.
    """
    if not chunk_ids:
        return {}
    try:
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(
                    ChunkModel.id,
                    ChunkModel.section_id,
                    ChunkModel.pdf_page_number,
                    ChunkModel.pdf_page_label,
                    ChunkModel.start_time,
                    SectionModel.heading,
                )
                .outerjoin(SectionModel, SectionModel.id == ChunkModel.section_id)
                .where(ChunkModel.id.in_(chunk_ids))
            )
            return {
                row.id: ChunkLocation(
                    section_id=row.section_id,
                    pdf_page=row.pdf_page_number,
                    pdf_page_label=row.pdf_page_label,
                    heading=row.heading,
                    start_time=row.start_time,
                )
                for row in rows
            }
    except Exception:
        logger.warning("fetch_chunk_locations: DB lookup failed", exc_info=True)
        return {}
