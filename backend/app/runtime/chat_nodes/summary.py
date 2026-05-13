"""summary_node and its DB helpers.

intent='summary' path: serve cached executive summaries (per-doc or
library-wide). Single-doc returns the cached summary as section_context
so synthesize_node still tailors to the question; library-wide returns
the cached LibrarySummaryModel directly with confidence='high'.
"""

import asyncio
import logging

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import (
    DocumentModel,
    LibrarySummaryModel,
    SummaryModel,
)
from app.runtime.chat_nodes._shared import _background_tasks
from app.services.summarizer import get_summarization_service
from app.types import ChatState

logger = logging.getLogger(__name__)


async def _fetch_single_doc_executive_summary(doc_id: str) -> str | None:
    """Return executive summary content for a single document, or None if absent."""
    async with get_session_factory()() as session:
        row = await session.execute(
            select(SummaryModel.content)
            .where(
                SummaryModel.document_id == doc_id,
                SummaryModel.mode == "executive",
            )
            .order_by(SummaryModel.created_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


async def _fetch_all_doc_executive_summaries() -> list[tuple[str, str]]:
    """Return (document_title, summary_content) for every doc that has an executive summary.

    Fetches the latest executive summary per document via a single joined query.
    Returns an empty list if none exist.
    """
    async with get_session_factory()() as session:

        # Latest created_at per document_id
        latest_subq = (
            select(
                SummaryModel.document_id,
                func.max(SummaryModel.created_at).label("max_ts"),
            )
            .where(SummaryModel.mode == "executive")
            .group_by(SummaryModel.document_id)
            .subquery()
        )
        rows = await session.execute(
            select(DocumentModel.title, SummaryModel.content)
            .join(DocumentModel, DocumentModel.id == SummaryModel.document_id)
            .join(
                latest_subq,
                (SummaryModel.document_id == latest_subq.c.document_id)
                & (SummaryModel.created_at == latest_subq.c.max_ts),
            )
            .order_by(DocumentModel.title)
        )
        return [(row.title, row.content) for row in rows]


async def _fetch_library_executive_summary() -> str | None:
    """Return the most recent library-level executive summary, or None if absent."""
    async with get_session_factory()() as session:
        row = await session.execute(
            select(LibrarySummaryModel.content)
            .where(LibrarySummaryModel.mode == "executive")
            .order_by(LibrarySummaryModel.created_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


async def _generate_library_summary_task() -> None:
    """Background coroutine: trigger executive library summary generation and storage."""

    svc = get_summarization_service()
    try:
        async for _ in svc.stream_library_summary(
            mode="executive", model=None, force_refresh=False
        ):
            pass  # consuming the generator triggers generation + storage
    except Exception:
        logger.warning("_generate_library_summary_task: failed", exc_info=True)


async def summary_node(state: ChatState) -> dict:
    """Fetch executive summary from DB; fall through to search if absent.

    scope='single': fetch this document's executive summary and set answer directly
                    (no LLM call — the cached summary IS the answer).
    scope='all':    fetch per-document executive summaries for ALL docs in parallel,
                    format them as section_context so synthesize_node calls the LLM
                    to synthesize a cross-library answer with proper citations.
    """
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")

    logger.info("summary_node: scope=%s", scope)

    if scope == "single" and doc_ids:
        try:
            summary_content = await _fetch_single_doc_executive_summary(doc_ids[0])
        except Exception:
            logger.warning("summary_node: single-doc DB lookup failed", exc_info=True)
            summary_content = None

        if not summary_content:
            logger.info(
                "summary_node: no cached summary for doc %s — falling through to search",
                doc_ids[0],
            )
            return {"intent": "factual"}

        logger.info(
            "summary_node: passing cached summary (%d chars) as context for LLM tailoring",
            len(summary_content),
        )
        # Pass as section_context rather than answer so synthesize_node calls the LLM
        # to answer the specific question.  Returning the full executive summary as
        # `answer` bypasses the LLM and gives every question the same cached text.
        return {
            "section_context": f"[Document Summary]\n{summary_content}",
            "chunks": [],
        }

    # scope='all': use pre-computed LibrarySummaryModel if available
    try:
        library_summary = await _fetch_library_executive_summary()
    except Exception:
        logger.warning("summary_node: library summary DB lookup failed", exc_info=True)
        library_summary = None

    if library_summary:
        logger.info(
            "summary_node: serving cached library summary (%d chars)",
            len(library_summary),
        )
        return {
            "answer": library_summary,
            "confidence": "high",
            "chunks": [],
        }

    # No library summary yet — check how many docs exist before deciding what to do
    try:
        all_summaries = await _fetch_all_doc_executive_summaries()
    except Exception:
        logger.warning("summary_node: all-doc summaries lookup failed", exc_info=True)
        all_summaries = []

    if len(all_summaries) == 1:
        # Single-document library: skip the cross-library path and serve that doc's summary
        title, content = all_summaries[0]
        logger.info(
            "summary_node: single-doc library — serving '%s' summary as section_context",
            title,
        )
        return {
            "section_context": f"[Document Summary: {title}]\n{content}",
            "chunks": [],
        }

    # Multiple docs but no cached library summary yet — fire background generation
    logger.info("summary_node: no library summary found — firing background generation")
    task = asyncio.create_task(_generate_library_summary_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "answer": ("The library summary is being generated. Please ask again in a moment."),
        "confidence": "medium",
        "not_found": False,
    }
