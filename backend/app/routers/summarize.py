"""Summarization endpoints — cache-first, SSE streaming."""

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_session_factory
from app.models import DocumentModel
from app.repos._helpers import get_or_404
from app.repos.summary_repo import SummaryRepo
from app.services.library_summary import get_library_summary_service
from app.services.summarizer import get_summarization_service
from app.streaming import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/summarize", tags=["summarize"])


class SummarizeRequest(BaseModel):
    mode: Literal["one_sentence", "executive", "detailed", "conversation"]
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
        rows = await SummaryRepo(session).section_summaries(document_id)
    return [{"unit_index": r.unit_index, "heading": r.heading, "content": r.content} for r in rows]


@router.get("/{document_id}/cached")
async def get_cached_summaries(document_id: str) -> dict:
    """Return which summary modes are already cached for this document.

    The frontend calls this on document open to decide whether to show
    a pre-loaded summary or a Generate button.
    """
    async with get_session_factory()() as session:
        latest = await SummaryRepo(session).latest_by_mode(document_id)
    summaries = {mode: {"id": row.id, "content": row.content} for mode, row in latest.items()}
    return {"document_id": document_id, "summaries": summaries}


@router.post("/all")
async def summarize_library(req: LibrarySummarizeRequest) -> StreamingResponse:
    """Stream a holistic summary synthesized from all ingested documents.

    Cache-first: if a library summary is stored for this mode it is streamed from
    the database.  Regenerated after any new document is ingested.
    """
    svc = get_library_summary_service()
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
        await get_or_404(session, DocumentModel, document_id, name="Document")

    svc = get_summarization_service()
    return StreamingResponse(
        svc.stream_summary(document_id, req.mode, req.model, force_refresh=req.force_refresh),
        media_type="text/event-stream",
    )
