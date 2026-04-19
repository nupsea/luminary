import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import ChunkModel, SectionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sections", tags=["sections"])


class SectionContentItem(BaseModel):
    section_id: str
    heading: str
    level: int
    section_order: int
    content: str


class SectionResponse(BaseModel):
    id: str
    heading: str
    level: int
    page_start: int
    section_order: int
    chunk_count: int
    has_summary: bool
    admonition_type: str | None = None
    parent_section_id: str | None = None


@router.get("/{document_id}", response_model=list[SectionResponse])
async def get_sections(document_id: str) -> list[SectionResponse]:
    """Return sections for a document with accurate chunk_count per section."""
    async with get_session_factory()() as session:
        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        sections = sections_result.scalars().all()

        if not sections:
            return []

        # Batch chunk counts per section in a single query
        chunk_counts_result = await session.execute(
            select(ChunkModel.section_id, func.count(ChunkModel.id))
            .where(
                ChunkModel.document_id == document_id,
                ChunkModel.section_id.isnot(None),
            )
            .group_by(ChunkModel.section_id)
        )
        chunk_counts: dict[str, int] = {row[0]: row[1] for row in chunk_counts_result.all()}

    logger.debug("Sections fetched", extra={"document_id": document_id, "count": len(sections)})
    return [
        SectionResponse(
            id=s.id,
            heading=s.heading,
            level=s.level,
            page_start=s.page_start,
            section_order=s.section_order,
            chunk_count=chunk_counts.get(s.id, 0),
            # Section-level summaries not yet implemented — always False.
            has_summary=False,
            admonition_type=s.admonition_type,
            parent_section_id=s.parent_section_id,
        )
        for s in sections
    ]


@router.get("/{document_id}/content", response_model=list[SectionContentItem])
async def get_section_content(document_id: str) -> list[SectionContentItem]:
    """Return all sections with full text assembled from their chunks."""
    async with get_session_factory()() as session:
        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        sections = sections_result.scalars().all()

        if not sections:
            return []

        chunks_result = await session.execute(
            select(ChunkModel)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.section_id, ChunkModel.chunk_index)
        )
        chunks = chunks_result.scalars().all()

    # Group chunks by section_id; orphan chunks (section_id=None) go into a separate list
    chunks_by_section: dict[str, list[str]] = {}
    orphan_chunks: list[str] = []
    for c in chunks:
        if c.section_id:
            chunks_by_section.setdefault(c.section_id, []).append(c.text)
        else:
            orphan_chunks.append(c.text)

    # Prefer the original section text (preview) over chunk-reassembled text.
    # Chunks contain enrichment prefixes like "[Title > Section] ..." that are
    # useful for retrieval but hurt the reading experience.  The preview field
    # stores up to 10 000 chars of the original parsed section text -- if the
    # section is longer, the preview is truncated mid-sentence and we must fall
    # back to chunk-assembled text (with enrichment headers stripped).
    PREVIEW_LIMIT = 10000

    def _section_content(s: SectionModel) -> str:
        chunk_texts = chunks_by_section.get(s.id, [])
        # If preview exists and is NOT truncated (shorter than the storage cap),
        # use it -- it preserves original formatting.
        if s.preview and len(s.preview) < PREVIEW_LIMIT:
            return s.preview
        # Preview was truncated or empty -- reassemble from chunks, stripping
        # the "[Title > Section] " enrichment prefix from each chunk.
        if chunk_texts:
            return "\n\n".join(re.sub(r"^\[.*?\]\s*", "", c) for c in chunk_texts)
        # Last resort: return whatever preview we have, even if truncated
        return s.preview or ""

    result = [
        SectionContentItem(
            section_id=s.id,
            heading=s.heading,
            level=s.level,
            section_order=s.section_order,
            content=_section_content(s),
        )
        for s in sections
    ]

    # If all sections ended up empty (chunks lacked section_id mapping),
    # distribute orphan chunks evenly across sections as a best-effort fallback.
    # Strip enrichment headers ([...] prefix) so the text reads naturally.
    if orphan_chunks and all(not r.content for r in result) and result:
        cleaned = [re.sub(r"^\[.*?\]\s*", "", c) for c in orphan_chunks]
        per_section = max(1, len(cleaned) // len(result))
        for i, item in enumerate(result):
            start = i * per_section
            end = start + per_section if i < len(result) - 1 else len(cleaned)
            item.content = "\n\n".join(cleaned[start:end])

    return result
