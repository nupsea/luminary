"""Summarization endpoints — cache-first, SSE streaming."""

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, SectionSummaryModel, SummaryModel
from app.repos._helpers import get_or_404
from app.services.summarizer import get_summarization_service

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
        # Custom 3-column projection for this endpoint's list response; no SectionSummaryRepo
        # method would be cleaner given the caller shapes the columns.
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

    If a summary is missing or is an unreadable legacy dump/stub, attempts
    fast assembly from pre-computed section summaries so the user gets an
    instant, high-quality summary on open.
    """
    svc = get_summarization_service()
    async with get_session_factory()() as session:
        # Custom projection + dedup-by-mode fold; the caller owns the fold logic so this stays
        # in the router rather than being wrapped in a SummaryRepo method.
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

    # Automatically assemble and cache executive / detailed if missing or bad legacy
    for mode in ("executive", "detailed"):
        needs_refresh = False
        if mode not in summaries:
            needs_refresh = True
        else:
            content = summaries[mode]["content"]
            # Detailed: old 220KB raw unreadable dump or starting with boilerplate
            # Executive: old 3-bullet stub under 600 chars on large documents
            if (
                mode == "detailed"
                and (len(content) > 60_000 or content.startswith("## Praise for"))
            ) or (
                mode == "executive"
                and len(content) < 600
                and "### Key Takeaways" not in content
            ):
                needs_refresh = True

        if needs_refresh:
            assembled = await svc.build_assembled_summary(document_id, mode)
            if assembled:
                summary_id = await svc._store_summary(document_id, mode, assembled)
                summaries[mode] = {"id": summary_id, "content": assembled}

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
        await get_or_404(session, DocumentModel, document_id, name="Document")

    svc = get_summarization_service()
    return StreamingResponse(
        svc.stream_summary(document_id, req.mode, req.model, force_refresh=req.force_refresh),
        media_type="text/event-stream",
    )
