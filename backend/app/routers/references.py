"""Web reference endpoints for S138.

Routes:
  GET  /references/documents/{document_id}      -- all refs for a document
  GET  /references/sections/{section_id}        -- refs for a section
  POST /references/sections/{section_id}/refresh -- re-run extraction for a section
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, WebReferenceModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/references", tags=["references"])

# ~18 months expressed in days
_OUTDATED_DAYS = 548


def _is_outdated(created_at: datetime) -> bool:
    """Return True if the reference was created more than 18 months ago."""
    cutoff = datetime.now(UTC) - timedelta(days=_OUTDATED_DAYS)
    aware = created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
    return aware < cutoff


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class WebReferenceItem(BaseModel):
    id: str
    section_id: str | None
    term: str
    url: str
    title: str
    excerpt: str
    source_quality: str
    is_llm_suggested: bool
    created_at: datetime
    is_outdated: bool

    model_config = {"from_attributes": True}


class DocumentReferencesResponse(BaseModel):
    document_id: str
    references: list[WebReferenceItem]


class SectionReferencesResponse(BaseModel):
    section_id: str
    references: list[WebReferenceItem]


def _to_item(row: WebReferenceModel) -> WebReferenceItem:
    return WebReferenceItem(
        id=row.id,
        section_id=row.section_id,
        term=row.term,
        url=row.url,
        title=row.title,
        excerpt=row.excerpt,
        source_quality=row.source_quality,
        is_llm_suggested=row.is_llm_suggested,
        created_at=row.created_at,
        is_outdated=_is_outdated(row.created_at),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}", response_model=DocumentReferencesResponse)
async def get_document_references(document_id: str) -> DocumentReferencesResponse:
    """Return all web references for a document, ordered by source_quality then term.

    Returns empty list (not 404) when the document exists but has no references.
    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        doc_result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        if doc_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Document not found")

        refs_result = await session.execute(
            select(WebReferenceModel)
            .where(WebReferenceModel.document_id == document_id)
            .order_by(WebReferenceModel.source_quality, WebReferenceModel.term)
        )
        rows = refs_result.scalars().all()

    return DocumentReferencesResponse(
        document_id=document_id,
        references=[_to_item(r) for r in rows],
    )


@router.get("/sections/{section_id}", response_model=SectionReferencesResponse)
async def get_section_references(section_id: str) -> SectionReferencesResponse:
    """Return web references for a single section, ordered by source_quality."""
    async with get_session_factory()() as session:
        refs_result = await session.execute(
            select(WebReferenceModel)
            .where(WebReferenceModel.section_id == section_id)
            .order_by(WebReferenceModel.source_quality, WebReferenceModel.term)
        )
        rows = refs_result.scalars().all()

    return SectionReferencesResponse(
        section_id=section_id,
        references=[_to_item(r) for r in rows],
    )


@router.post("/sections/{section_id}/refresh", status_code=202)
async def refresh_section_references(
    section_id: str,
    document_id: str = Query(..., description="Parent document ID"),
) -> dict:
    """Re-run LLM extraction for a section (used by 'Outdated?' refresh button).

    Returns 202 Accepted immediately; extraction runs synchronously.
    Returns 503 if Ollama is unreachable.
    """
    from app.services.reference_enricher import ReferenceEnricherService  # noqa: PLC0415

    svc = ReferenceEnricherService()
    count = await svc.refresh_section(section_id=section_id, document_id=document_id)
    logger.info(
        "refresh_section_references: section_id=%s doc=%s inserted=%d",
        section_id,
        document_id,
        count,
    )
    return {"section_id": section_id, "inserted": count}
