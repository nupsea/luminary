"""Web reference endpoints for S138 + S194.

Routes:
  GET  /references/documents/{document_id}              -- refs for a document
  POST /references/documents/{document_id}/validate     -- validate ref URLs
  POST /references/documents/{document_id}/refresh      -- re-extract + validate all
  GET  /references/sections/{section_id}                -- refs for a section
  POST /references/sections/{section_id}/refresh        -- re-run extraction for a section
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, WebReferenceModel
from app.services.repo_helpers import get_or_404

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
    is_valid: bool | None = None
    last_checked_at: datetime | None = None
    created_at: datetime
    is_outdated: bool

    model_config = {"from_attributes": True}


class DocumentReferencesResponse(BaseModel):
    document_id: str
    references: list[WebReferenceItem]


class SectionReferencesResponse(BaseModel):
    section_id: str
    references: list[WebReferenceItem]


class ValidateResponse(BaseModel):
    document_id: str
    valid: int
    invalid: int


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
        is_valid=row.is_valid,
        last_checked_at=row.last_checked_at,
        created_at=row.created_at,
        is_outdated=_is_outdated(row.created_at),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}", response_model=DocumentReferencesResponse)
async def get_document_references(
    document_id: str,
    include_invalid: bool = Query(False, description="Include is_valid=False refs"),
) -> DocumentReferencesResponse:
    """Return web references for a document, ordered by source_quality then term.

    By default, excludes is_valid=False rows. Pass include_invalid=true to include all.
    is_valid=None (unchecked) rows are always included.
    Returns empty list (not 404) when the document exists but has no references.
    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        query = (
            select(WebReferenceModel)
            .where(WebReferenceModel.document_id == document_id)
            .order_by(WebReferenceModel.source_quality, WebReferenceModel.term)
        )
        if not include_invalid:
            # Exclude explicitly invalid refs; keep unchecked (None) and valid (True)
            query = query.where(
                (WebReferenceModel.is_valid.is_(None)) | (WebReferenceModel.is_valid == True)  # noqa: E712
            )
        refs_result = await session.execute(query)
        rows = refs_result.scalars().all()

    return DocumentReferencesResponse(
        document_id=document_id,
        references=[_to_item(r) for r in rows],
    )


# NOTE: POST validate and refresh routes registered BEFORE /{document_id}
# wildcard to prevent FastAPI from matching "validate" as a document_id.


@router.post("/documents/{document_id}/validate", response_model=ValidateResponse)
async def validate_document_references(document_id: str) -> ValidateResponse:
    """Run HEAD requests against all reference URLs for a document.

    Updates is_valid and last_checked_at per reference.
    """
    from app.services.reference_validator import ReferenceValidatorService  # noqa: PLC0415

    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

    svc = ReferenceValidatorService()
    counts = await svc.validate_references(document_id)
    return ValidateResponse(
        document_id=document_id,
        valid=counts["valid"],
        invalid=counts["invalid"],
    )


@router.post("/documents/{document_id}/refresh", status_code=202)
async def refresh_document_references(document_id: str) -> dict:
    """Re-run extraction + validation for all sections of a document.

    Deletes existing refs, re-extracts from section summaries, validates URLs.
    """
    from app.services.reference_enricher import ReferenceEnricherService  # noqa: PLC0415

    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        # Delete all existing refs for this document
        existing = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.document_id == document_id)
        )
        for row in existing.scalars().all():
            await session.delete(row)
        await session.commit()

    # Re-extract (enrich() internally validates URLs via _validate_urls)
    enricher = ReferenceEnricherService()
    count = await enricher.enrich(document_id)

    # Count valid/invalid from the newly persisted refs
    async with get_session_factory()() as session:
        refs_result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.document_id == document_id)
        )
        rows = refs_result.scalars().all()

    valid = sum(1 for r in rows if r.is_valid is True)
    invalid = sum(1 for r in rows if r.is_valid is False)

    return {
        "document_id": document_id,
        "extracted": count,
        "valid": valid,
        "invalid": invalid,
    }


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
