import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import ChunkModel, SectionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sections", tags=["sections"])


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
