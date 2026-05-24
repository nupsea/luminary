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
import uuid

from sqlalchemy import update as _update

from app.database import get_session_factory
from app.models import DocumentModel, EnrichmentJobModel
from app.services.document_tagger import enrich_document_tags
from app.services.enrichment_worker import get_enrichment_worker
from app.services.section_summarizer import get_section_summarizer_service
from app.services.summarizer import get_summarization_service
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _background_tasks,
    _update_stage,
)

logger = logging.getLogger(__name__)


async def _run_pregenerate(doc_id: str) -> None:
    """Background task: pre-generate summaries and invalidate library cache."""

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
    """Pass-through: summary pre-generation is deferred to enrichment_enqueue_node.

    Background task creation is intentionally consolidated in enrichment_enqueue_node
    so that all async work starts AFTER _update_stage("complete") commits on the
    shared StaticPool connection — preventing concurrent DB writes from racing with
    the stage update.
    """
    return state


async def error_finalize_node(state: IngestionState) -> IngestionState:
    """Terminal node reached when any upstream node sets status='error'.

    Persists the human-readable error detail to DocumentModel.error_message so
    GET /documents/{id}/status can surface it to the UI (e.g. 'ffmpeg not found').
    """


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

    Job rows are written to the DB first. _update_stage("complete") is called
    before any asyncio.create_task so that the worker's concurrent DB writes
    do not race with the stage update (SQLite allows only one writer at a time).
    """
    doc_id = state["document_id"]
    fmt = state.get("format", "").lower()
    _IMAGE_FORMATS = {"pdf", "epub", "md", "markdown"}

    # Phase 1: write all job rows to DB (no background tasks yet).
    needs_dispatch = False

    if fmt in _IMAGE_FORMATS:
        try:
            job_id = str(uuid.uuid4())
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
            needs_dispatch = True
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

    try:
        cl_job_id = str(uuid.uuid4())
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
        needs_dispatch = True
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

    # Phase 2: mark complete BEFORE creating background tasks.
    # asyncio.create_task schedules work that runs at the next await; if tasks
    # were created earlier, _dispatch_pending would race with this write for the
    # SQLite write lock and intermittently fail (leaving stage='indexing').
    await _update_stage(doc_id, "complete")

    # Phase 3: schedule all background tasks (no await between here and return,
    # so they do not start until after this node returns to LangGraph and the
    # stage='complete' commit is fully visible).
    # _run_pregenerate is created here (not in summarize_node) so the shared
    # StaticPool connection is free of concurrent writers when _update_stage runs.
    try:
        pregenerate_task = asyncio.create_task(_run_pregenerate(doc_id))
        _background_tasks.add(pregenerate_task)
        pregenerate_task.add_done_callback(_background_tasks.discard)
    except Exception as exc:
        logger.warning(
            "enrichment_enqueue_node: pregenerate schedule failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    # Auto-tag enrichment (2D.1). Scheduled after stage='complete' commits so
    # tag writes never gate the doc becoming usable. Failures are logged and
    # do not propagate.
    try:
        auto_tag_task = asyncio.create_task(enrich_document_tags(doc_id))
        _background_tasks.add(auto_tag_task)
        auto_tag_task.add_done_callback(_background_tasks.discard)
    except Exception as exc:
        logger.warning(
            "enrichment_enqueue_node: auto-tag schedule failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    if needs_dispatch:
        try:
            worker = get_enrichment_worker()
            dispatch_task = asyncio.create_task(worker._dispatch_pending())
            _background_tasks.add(dispatch_task)
            dispatch_task.add_done_callback(_background_tasks.discard)
        except Exception as exc:
            logger.warning(
                "enrichment_enqueue_node: dispatch failed (non-fatal): %s",
                exc,
                extra={"doc_id": doc_id},
            )

    return {**state, "status": "complete"}

