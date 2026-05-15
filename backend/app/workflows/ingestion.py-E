import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.telemetry import trace_chain
from app.workflows.ingestion_nodes._shared import (
    CHUNK_CONFIGS,  # noqa: F401  re-exported for back-compat
    ENTITY_TAIL_MAX,  # noqa: F401  re-exported for back-compat
    STAGE_PROGRESS,  # noqa: F401  re-exported for routers/documents.py
    ContentType,  # noqa: F401  re-exported for back-compat
    IngestionState,
    _background_tasks,  # noqa: F401  re-exported for tests/test_integration.py
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
from app.workflows.ingestion_nodes.finalize import (
    _run_pregenerate,  # noqa: F401  re-exported for tests/test_ingestion_perf
    enrichment_enqueue_node,
    error_finalize_node,
    section_summarize_node,
    summarize_node,
)
from app.workflows.ingestion_nodes.parse import classify_node, parse_node
from app.workflows.ingestion_nodes.transcribe import (
    _chunk_audio,  # noqa: F401  re-exported for back-compat (tests/test_audio_ingestion.py)
    transcribe_node,
)

logger = logging.getLogger(__name__)





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
