import logging
from typing import Any

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

from app.telemetry import trace_chain
from app.types import MEDIA_FORMATS
from app.workflows.ingestion_nodes._shared import (
    ENTITY_TAIL_MAX,  # noqa: F401  re-exported for back-compat
    IngestionState,
    _background_tasks,  # noqa: F401  re-exported for tests/test_integration.py
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
    chunk_book_node,
    chunk_code_node,
    chunk_conversation_node,
    chunk_generic_node,
    chunk_paper_node,
    chunk_tech_book_node,
    chunk_transcript_node,
    route_chunker,
)
from app.workflows.ingestion_nodes.embed import VectorCountMismatch, embed_node, keyword_index_node
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

CHUNKERS = (
    "chunk_code",
    "chunk_tech_book",
    "chunk_book",
    "chunk_conversation",
    "chunk_paper",
    "chunk_generic",
)


def _to_error_finalize(state: IngestionState, error: NodeError) -> Command:
    """Any node that raises ends the run at error_finalize, which records the message."""
    logger.error(
        "ingestion node %s failed",
        error.node,
        exc_info=error.error,
        extra={"document_id": state["document_id"]},
    )
    return Command(goto="error_finalize", update={"status": "error", "error": str(error.error)})


def _after_classify(state: IngestionState) -> str:
    # Media has no text until transcription; its chunks are the transcript's windows.
    return "transcribe" if state["format"] in MEDIA_FORMATS else route_chunker(state)


def _build_graph():
    builder: StateGraph = StateGraph(IngestionState)

    def node(name: str, action, **policies) -> None:
        builder.add_node(name, action, error_handler=_to_error_finalize, **policies)

    node("parse", parse_node)
    node("classify", classify_node)
    node("transcribe", transcribe_node)
    node("chunk_transcript", chunk_transcript_node)
    node("chunk_code", chunk_code_node)
    node("chunk_tech_book", chunk_tech_book_node)
    node("chunk_book", chunk_book_node)
    node("chunk_conversation", chunk_conversation_node)
    node("chunk_paper", chunk_paper_node)
    node("chunk_generic", chunk_generic_node)
    node("entity_extract", entity_extract_node)
    embed_retry = RetryPolicy(max_attempts=2, retry_on=VectorCountMismatch)
    node("embed", embed_node, retry_policy=embed_retry)
    node("keyword_index", keyword_index_node)
    node("section_summarize", section_summarize_node)
    node("summarize", summarize_node)
    node("enrichment_enqueue", enrichment_enqueue_node)
    # No handler of its own: a failure here fails the run, and run_ingestion records it.
    builder.add_node("error_finalize", error_finalize_node)

    builder.add_edge(START, "parse")
    builder.add_edge("parse", "classify")
    builder.add_conditional_edges("classify", _after_classify, ["transcribe", *CHUNKERS])
    builder.add_edge("transcribe", "chunk_transcript")
    for chunker in ("chunk_transcript", *CHUNKERS):
        builder.add_edge(chunker, "entity_extract")
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
    parsed_document: dict[str, Any] | None = None,
    kind: str | None = None,
) -> None:
    initial_state: IngestionState = {
        "document_id": document_id,
        "file_path": file_path,
        "format": format,
        "parsed_document": parsed_document,
        "kind": kind,
        "chunks": None,
        "status": "parsing" if parsed_document is None else "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }
    logger.info(
        "Ingestion task started",
        extra={"document_id": document_id, "format": format, "kind": kind},
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
            logger.exception(
                "Ingestion task failed",
                extra={"document_id": document_id},
                exc_info=exc,
            )
            await _update_stage(document_id, "error")
