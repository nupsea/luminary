"""Pipeline tail: section_summarize, summarize, error_finalize, enrichment_enqueue.

These five small nodes complete the ingestion pipeline:

- _run_pregenerate          background helper that triggers post-ingest
                            summary pre-generation + library-summary
                            cache invalidation
- section_summarize_node    populates SectionSummaryModel rows for
                            qualifying sections (delegates to a service)
- summarize_node            sets stage='complete' and fires _run_pregenerate
- error_finalize_node       writes stage='error' on a failed run
- enrichment_enqueue_node   enqueues image / diagram / hypothesis / KaTeX
                            enrichment jobs and pokes the worker
"""

import asyncio
import logging

from app.database import get_session_factory
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _background_tasks,
    _update_stage,
)

logger = logging.getLogger(__name__)


async def _run_pregenerate(doc_id: str) -> None:
    """Background task: pre-generate summaries and invalidate library cache."""
    from app.services.summarizer import get_summarization_service  # noqa: PLC0415

    svc = get_summarization_service()
    try:
        await svc.generate_all_summaries(doc_id)
        logger.info("background summarize: done", extra={"doc_id": doc_id})
    except Exception as exc:
        logger.warning(
            "background summarize: failed (non-fatal)",
            extra={"doc_id": doc_id},
            exc_info=exc,
        )
    finally:
        # Always invalidate library cache — a new document was ingested regardless
        # of whether its individual summaries could be generated (e.g. Ollama offline).
        await svc.invalidate_library_cache()


async def section_summarize_node(state: IngestionState) -> IngestionState:
    """Generate section-level summaries (bounded to 100 units) before document summarization.

    Non-fatal: if Ollama is offline or summarization fails, ingestion continues.
    """
    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "section_summarize", "doc_id": doc_id})
    try:
        from app.services.section_summarizer import get_section_summarizer_service  # noqa: PLC0415

        svc = get_section_summarizer_service()
        count = await svc.generate(doc_id)
        logger.info("section_summarize_node: %d units stored", count, extra={"doc_id": doc_id})
        return {**state, "section_summary_count": count}
    except Exception as exc:
        logger.warning(
            "section_summarize_node failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )
        return {**state, "section_summary_count": 0}


async def summarize_node(state: IngestionState) -> IngestionState:
    """Fire off summary pre-generation as a background task and return immediately.

    The document is already marked complete by entity_extract_node.  Summaries
    generate asynchronously so ingestion does not block on LLM calls.
    """
    doc_id = state["document_id"]
    task = asyncio.create_task(_run_pregenerate(doc_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.info("summarize_node: background task scheduled", extra={"doc_id": doc_id})
    return state


async def error_finalize_node(state: IngestionState) -> IngestionState:
    """Terminal node reached when any upstream node sets status='error'.

    Persists the human-readable error detail to DocumentModel.error_message so
    GET /documents/{id}/status can surface it to the UI (e.g. 'ffmpeg not found').
    """
    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    doc_id = state["document_id"]
    error_detail = state.get("error")
    async with get_session_factory()() as session:
        await session.execute(
            _update(DocumentModel)
            .where(DocumentModel.id == doc_id)
            .values(stage="error", error_message=error_detail)
        )
        await session.commit()
    logger.error(
        "Ingestion failed at node",
        extra={"document_id": doc_id, "error": error_detail},
    )
    return state


async def enrichment_enqueue_node(state: IngestionState) -> IngestionState:
    """Create enrichment jobs: image_extract (PDF/EPUB only) and concept_link (always).

    Non-fatal: enrichment failure does not prevent document from being usable.
    """
    import uuid as _uuid  # noqa: PLC0415

    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel, EnrichmentJobModel  # noqa: PLC0415
    from app.services.enrichment_worker import get_enrichment_worker  # noqa: PLC0415

    doc_id = state["document_id"]
    fmt = state.get("format", "").lower()
    _IMAGE_FORMATS = {"pdf", "epub", "md", "markdown"}

    # Image extraction: PDF, EPUB, and MD (web articles)
    if fmt in _IMAGE_FORMATS:
        try:
            job_id = str(_uuid.uuid4())
            async with get_session_factory()() as session:
                session.add(
                    EnrichmentJobModel(
                        id=job_id,
                        document_id=doc_id,
                        job_type="image_extract",
                        status="pending",
                    )
                )
                await session.execute(
                    _update(DocumentModel)
                    .where(DocumentModel.id == doc_id)
                    .values(stage="enriching")
                )
                await session.commit()

            worker = get_enrichment_worker()
            task = asyncio.create_task(worker._dispatch_pending())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

            logger.info(
                "enrichment_enqueue_node: enqueued image_extract job=%s doc=%s",
                job_id,
                doc_id,
            )
        except Exception as exc:
            logger.warning(
                "enrichment_enqueue_node: image_extract enqueue failed (non-fatal): %s",
                exc,
                extra={"doc_id": doc_id},
            )
    else:
        logger.info(
            "enrichment_enqueue_node: skipping image_extract (format=%s has no images)",
            fmt,
            extra={"doc_id": doc_id},
        )

    # Concept linking: always enqueue for cross-document concept comparison (S141)
    try:
        cl_job_id = str(_uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                EnrichmentJobModel(
                    id=cl_job_id,
                    document_id=doc_id,
                    job_type="concept_link",
                    status="pending",
                )
            )
            await session.commit()

        worker = get_enrichment_worker()
        task = asyncio.create_task(worker._dispatch_pending())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        logger.info(
            "enrichment_enqueue_node: enqueued concept_link job=%s doc=%s",
            cl_job_id,
            doc_id,
        )
    except Exception as exc:
        logger.warning(
            "enrichment_enqueue_node: concept_link enqueue failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    await _update_stage(doc_id, "complete")
    return {**state, "status": "complete"}

