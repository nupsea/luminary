import asyncio
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.database import get_session_factory
from app.telemetry import trace_chain
from app.workflows.ingestion_nodes._shared import (
    CHUNK_CONFIGS,  # noqa: F401  re-exported for back-compat
    ENTITY_TAIL_MAX,  # noqa: F401  re-exported for back-compat
    STAGE_PROGRESS,  # noqa: F401  re-exported for routers/documents.py
    ContentType,  # noqa: F401  re-exported for back-compat
    IngestionState,
    _background_tasks,
    _classify,  # noqa: F401  re-exported for back-compat (tests import from ingestion)
    _parser,  # noqa: F401  re-exported for back-compat
    _update_stage,
    build_entity_tail,  # noqa: F401  re-exported for back-compat
)
from app.workflows.ingestion_nodes.chunk import (
    _chunk_book,  # noqa: F401  re-exported for tests
    _chunk_code_file,  # noqa: F401  re-exported for tests
    _chunk_conversation,  # noqa: F401  re-exported for tests
    _chunk_tech_book,  # noqa: F401  re-exported for tests
    _run_objective_extraction,  # noqa: F401  re-exported for back-compat
    chunk_node,
)
from app.workflows.ingestion_nodes.embed import embed_node, keyword_index_node
from app.workflows.ingestion_nodes.entity_extract import (
    _build_call_graph,  # noqa: F401  re-exported for tests
    entity_extract_node,
)
from app.workflows.ingestion_nodes.parse import classify_node, parse_node
from app.workflows.ingestion_nodes.transcribe import (
    _chunk_audio,  # noqa: F401  re-exported for back-compat (tests/test_audio_ingestion.py)
    transcribe_node,
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


def _route_on_status(next_node: str):
    """Return a router that goes to error_finalize if status=='error', else next_node."""

    def _router(state: IngestionState) -> str:
        return "error_finalize" if state.get("status") == "error" else next_node

    return _router


def _build_graph():
    builder: StateGraph = StateGraph(IngestionState)
    builder.add_node("parse", parse_node)
    builder.add_node("classify", classify_node)
    builder.add_node("transcribe", transcribe_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("embed", embed_node)
    builder.add_node("keyword_index", keyword_index_node)
    builder.add_node("entity_extract", entity_extract_node)
    builder.add_node("section_summarize", section_summarize_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("enrichment_enqueue", enrichment_enqueue_node)
    builder.add_node("error_finalize", error_finalize_node)
    builder.add_edge(START, "parse")
    builder.add_conditional_edges("parse", _route_on_status("classify"))
    builder.add_conditional_edges("classify", _route_on_status("transcribe"))
    builder.add_conditional_edges("transcribe", _route_on_status("chunk"))
    builder.add_conditional_edges("chunk", _route_on_status("entity_extract"))
    builder.add_edge("entity_extract", "embed")
    builder.add_edge("embed", "keyword_index")
    builder.add_edge("keyword_index", "section_summarize")
    builder.add_edge("section_summarize", "summarize")
    builder.add_edge("summarize", "enrichment_enqueue")
    builder.add_edge("enrichment_enqueue", END)
    builder.add_edge("error_finalize", END)
    return builder.compile()


ingestion_graph = _build_graph()


async def run_ingestion(
    document_id: str,
    file_path: str,
    format: str,
    content_type: str | None = None,
    parsed_document: dict[str, Any] | None = None,
) -> None:
    initial_state: IngestionState = {
        "document_id": document_id,
        "file_path": file_path,
        "format": format,
        "parsed_document": parsed_document,
        "content_type": content_type,
        "chunks": None,
        "status": "parsing" if parsed_document is None else "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }
    logger.info(
        "Ingestion task started",
        extra={"document_id": document_id, "format": format, "content_type": content_type},
    )
    if parsed_document is None:
        await _update_stage(document_id, "parsing")
    else:
        await _update_stage(document_id, "classifying")
    with trace_chain(
        "ingestion.workflow",
        input_value=f"doc={document_id} format={format}",
    ) as root_span:
        root_span.set_attribute("ingestion.document_id", document_id)
        root_span.set_attribute("ingestion.format", format)
        try:
            await ingestion_graph.ainvoke(initial_state)
            root_span.set_attribute("output.value", "complete")
            logger.info("Ingestion task complete", extra={"document_id": document_id})
        except Exception as exc:
            root_span.set_attribute("error", True)
            root_span.set_attribute("error.message", str(exc))
            logger.error(
                "Ingestion task failed",
                extra={"document_id": document_id},
                exc_info=exc,
            )
            await _update_stage(document_id, "error")
