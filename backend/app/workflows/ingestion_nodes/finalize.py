"""Pipeline tail: section_summarize, summarize, error_finalize, enrichment_enqueue.

These small nodes complete the ingestion pipeline:

- _run_pregenerate              background helper that triggers post-ingest
                                summary pre-generation + library-summary
                                cache invalidation
- _run_progressive_summarization   deferred-section-summary path: seeds a few
                                section summaries, derives one_sentence/executive
                                from them, then finishes the rest (see its own
                                docstring for why the ordering matters)
- section_summarize_node        populates SectionSummaryModel rows for
                                qualifying sections (delegates to a service)
- summarize_node                sets stage='complete' and fires _run_pregenerate
- error_finalize_node           writes stage='error' on a failed run
- enrichment_enqueue_node       enqueues image / diagram / hypothesis / KaTeX
                                enrichment jobs and pokes the worker
"""

import asyncio
import logging
import uuid

from sqlalchemy import update as _update

from app.database import get_session_factory
from app.models import DocumentModel, EnrichmentJobModel
from app.services.activity_service import ActivityService
from app.services.document_tagger import enrich_document_tags
from app.services.enrichment_worker import get_enrichment_worker
from app.services.model_router import resolve
from app.services.section_summarizer import (
    defer_section_summaries,
    get_section_summarizer_service,
)
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
        # Always refresh the library summary — a new document was ingested regardless
        # of whether its individual summaries could be generated (e.g. Ollama offline).
        # Refreshed here rather than left for the next question to trigger: that put a
        # whole library synthesis in front of an Ask that had to wait for it.
        await svc.refresh_library_summary()


async def _run_progressive_summarization(doc_id: str) -> None:
    """Progressive summarization, without ever falling back to chunk map-reduce.

    A document-level summary needs SOME input, and the only two sources are
    chunks (map-reduce -- sequential, 30-90s per batch, up to 8 batches) or
    section summaries. Calling pregenerate() before any section summary
    exists -- the naive "generate the doc summary first" ordering -- forces
    the map-reduce path even on a document large enough to have >=3 sections,
    because summarizer.pregenerate()'s fast path can only see section
    summaries that are already stored. That nearly doubled total LLM calls in
    testing (12 -> 20 on a 10-section document) and made 'summarized' status
    arrive LATER, not sooner, since map-reduce runs sequentially while section
    summarization runs at concurrency=3 -- the opposite of the intended win.

    So this seeds just enough real section summaries first:
    1. generate_progressive() summarises the first FAST_PATH_MIN_UNITS sections.
    2. pregenerate() derives one_sentence/executive from those seed summaries via
       the existing section-summary fast path -- one short call each, no map-reduce.
    3. generate_progressive_rest() finishes the remaining sections.
    4. A final pregenerate() picks up 'detailed', assembled for free once every
       section has a summary -- one_sentence/executive are already cached.
    """
    section_svc = get_section_summarizer_service()
    seed_inserted, rest_units, next_index = 0, [], 0
    try:
        seed_inserted, rest_units, next_index = await section_svc.generate_progressive(doc_id)
        logger.info(
            "progressive summarize: seeded %d section summaries",
            seed_inserted,
            extra={"doc_id": doc_id},
        )
    except Exception as exc:
        logger.warning(
            "progressive summarize: section seed failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    if seed_inserted:
        try:
            await get_summarization_service().pregenerate(
                doc_id, modes=("one_sentence", "executive")
            )
            logger.info(
                "progressive summarize: fast document summaries stored",
                extra={"doc_id": doc_id},
            )
        except Exception as exc:
            logger.warning(
                "progressive summarize: fast document summaries failed (non-fatal): %s",
                exc,
                extra={"doc_id": doc_id},
            )

    try:
        rest_inserted = await section_svc.generate_progressive_rest(
            doc_id, rest_units, next_index
        )
        logger.info(
            "progressive summarize: %d remaining section summaries stored",
            rest_inserted,
            extra={"doc_id": doc_id},
        )
    except Exception as exc:
        logger.warning(
            "progressive summarize: remaining section summaries failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    await _run_pregenerate(doc_id)


async def section_summarize_node(state: IngestionState) -> IngestionState:
    """Generate section-level summaries before document summarization.

    Summaries move behind `stage='complete'` whenever generation is local --
    see `defer_section_summaries` -- so the document is readable while they
    fill in rather than after.

    Non-fatal: if Ollama is offline or summarization fails, ingestion continues.
    """
    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "section_summarize", "doc_id": doc_id})
    try:
        svc = get_section_summarizer_service()
        sections = await svc.qualifying_section_count(doc_id)
        # `sections` first: with nothing to summarise there is nothing to defer,
        # and scheduling the deferred task anyway left a background coroutine
        # running after every ingest of a document with no qualifying sections.
        # CI could not see it -- there is no Ollama there, so the task failed
        # instantly -- but against a live one test_e2e_upload went from 8s to
        # past the 120s pytest timeout, hanging in teardown on the loop that
        # task was still using.
        if sections and defer_section_summaries(sections, resolve("generation").model):
            logger.info(
                "section_summarize_node: deferring %d section summaries until after completion",
                sections,
                extra={"doc_id": doc_id},
            )
            return {**state, "section_summary_count": 0, "defer_section_summaries": True}

        await _update_stage(doc_id, "summarizing")
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

    # Persist parser word/page counts (chunk nodes only wrote chapter_count).
    # pd is None for audio/video, which set word_count in transcribe.
    pd = state.get("parsed_document")
    if pd:
        async with get_session_factory()() as session:
            await session.execute(
                _update(DocumentModel)
                .where(DocumentModel.id == doc_id)
                .values(
                    word_count=pd.get("word_count") or 0,
                    page_count=pd.get("pages") or 0,
                )
            )
            await session.commit()

    # Phase 2: mark complete BEFORE creating background tasks.
    # asyncio.create_task schedules work that runs at the next await; if tasks
    # were created earlier, _dispatch_pending would race with this write for the
    # SQLite write lock and intermittently fail (leaving stage='indexing').
    await _update_stage(doc_id, "complete")

    # The hub reads content_activity and nothing else, so without this a library
    # full of documents renders empty. On completion, not on upload: a failed
    # ingest must not surface as something to pick up.
    try:
        async with get_session_factory()() as session:
            await ActivityService(session).record_document_added(doc_id)
    except Exception as exc:
        logger.warning(
            "enrichment_enqueue_node: activity record failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    # Phase 3: schedule all background tasks (no await between here and return,
    # so they do not start until after this node returns to LangGraph and the
    # stage='complete' commit is fully visible).
    # _run_pregenerate is created here (not in summarize_node) so the shared
    # StaticPool connection is free of concurrent writers when _update_stage runs.
    try:
        # A deferred document runs progressive summarization: immediate executive
        # summary first (<15s) so the document reaches 'summarized' status right away,
        # followed by deferred section summaries and detailed assembly in background.
        deferred = state.get("defer_section_summaries")
        coro = _run_progressive_summarization(doc_id) if deferred else _run_pregenerate(doc_id)
        pregenerate_task = asyncio.create_task(coro)
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

