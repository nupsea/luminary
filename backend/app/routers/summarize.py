"""Summarization endpoints — cache-first, SSE streaming."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, SectionSummaryModel, SummaryModel
from app.services.summarizer import get_summarization_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/summarize", tags=["summarize"])


class SummarizeRequest(BaseModel):
    mode: Literal["one_sentence", "executive", "detailed", "conversation", "glossary"]
    model: str | None = None
    force_refresh: bool = False


class LibrarySummarizeRequest(BaseModel):
    mode: Literal["one_sentence", "executive", "detailed"] = "executive"
    model: str | None = None
    force_refresh: bool = False


@router.get("/{document_id}/sections")
async def get_section_summaries(document_id: str) -> list[dict]:
    """Return section summaries for a document, ordered by unit_index.

    Returns an empty list if no section summaries exist (pre-V2 documents or
    documents where section summarization was skipped due to Ollama being offline).
    """
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(
                SectionSummaryModel.unit_index,
                SectionSummaryModel.heading,
                SectionSummaryModel.content,
            )
            .where(SectionSummaryModel.document_id == document_id)
            .order_by(SectionSummaryModel.unit_index)
        )
        return [
            {"unit_index": r.unit_index, "heading": r.heading, "content": r.content} for r in rows
        ]


@router.get("/{document_id}/cached")
async def get_cached_summaries(document_id: str) -> dict:
    """Return which summary modes are already cached for this document.

    The frontend calls this on document open to decide whether to show
    a pre-loaded summary or a Generate button.
    """
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(SummaryModel.mode, SummaryModel.id, SummaryModel.content)
            .where(SummaryModel.document_id == document_id)
            .order_by(SummaryModel.created_at.desc())
        )
        # One entry per mode (most recent wins)
        seen: set[str] = set()
        summaries: dict[str, dict] = {}
        for row in rows:
            if row.mode not in seen:
                seen.add(row.mode)
                summaries[row.mode] = {"id": row.id, "content": row.content}
    return {"document_id": document_id, "summaries": summaries}


@router.post("/all")
async def summarize_library(req: LibrarySummarizeRequest) -> StreamingResponse:
    """Stream a holistic summary synthesized from all ingested documents.

    Cache-first: if a library summary is stored for this mode it is streamed from
    the database.  Regenerated after any new document is ingested.
    """
    svc = get_summarization_service()
    return StreamingResponse(
        svc.stream_library_summary(req.mode, req.model, force_refresh=req.force_refresh),
        media_type="text/event-stream",
    )


@router.post("/{document_id}")
async def summarize_document(document_id: str, req: SummarizeRequest) -> StreamingResponse:
    """Stream a summary for the given document and mode.

    Cache-first: if a summary is already stored it is streamed from the
    database without calling the LLM.  Generates and stores on cache miss.
    """
    async with get_session_factory()() as session:
        doc = (
            await session.execute(select(DocumentModel).where(DocumentModel.id == document_id))
        ).scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    svc = get_summarization_service()
    return StreamingResponse(
        svc.stream_summary(document_id, req.mode, req.model, force_refresh=req.force_refresh),
        media_type="text/event-stream",
    )
