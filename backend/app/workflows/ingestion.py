import asyncio
import logging
from pathlib import Path
from typing import Any

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

from app.database import get_session_factory
from app.models import DocumentModel
from app.repos.document_repo import DocumentRepo
from app.services.document_deletion_service import get_document_deletion_service
from app.services.ingestion_jobs import get_ingestion_jobs
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


# The stored stage says which rows are complete, and those rows are the checkpoint
# (I-74). An earlier stage leaves a partial parse, cleared and ingested from the file.
_RESUME_AT = {
    "embedding": "embed",
    "indexing": "section_summarize",
    "summarizing": "section_summarize",
}
_RESTART_FROM_FILE = frozenset(
    {"parsing", "classifying", "transcribing", "correcting", "chunking", "entity_extract"}
)
# One resume: a quit mid-ingest resumes, while a document that kills the process at
# every launch fails on the next one instead of looping.
MAX_INGEST_RESUMES = 1

_INTERRUPTED = (
    "Ingestion was interrupted before it finished. Delete this document and upload it again."
)
_INTERRUPTED_AGAIN = (
    "Ingestion was interrupted again after resuming. Delete this document and upload it again."
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


def _entry(state: IngestionState) -> str:
    return state.get("resume_from") or "parse"


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

    builder.add_conditional_edges(START, _entry, ["parse", *sorted(set(_RESUME_AT.values()))])
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
        "resume_from": None,
    }
    logger.info(
        "Ingestion task started",
        extra={"document_id": document_id, "format": format, "kind": kind},
    )
    if parsed_document is None:
        await _update_stage(document_id, "parsing")
    else:
        await _update_stage(document_id, "classifying")
    await _run_graph(initial_state)


async def resume_ingestion(document_id: str, resume_from: str) -> None:
    """Re-enter the graph at `resume_from`, reading what earlier stages stored."""
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        doc = await repo.get_or_404(document_id)
        chunks = [
            {
                "id": c.id,
                "document_id": document_id,
                "text": c.text,
                "index": c.chunk_index,
                "entities_text": c.entities_text,
            }
            for c in await repo.chunks_for_document(document_id)
        ]
    state: IngestionState = {
        "document_id": document_id,
        "file_path": doc.file_path,
        "format": doc.format,
        "parsed_document": None,
        "kind": None,
        "chunks": chunks,
        "status": "resuming",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": doc.audio_duration_seconds,
        "form": doc.form,
        "domain": doc.domain,
        "structure_type": doc.structure_type,
        "defer_section_summaries": None,
        "_audio_chunks": None,
        "resume_from": resume_from,
    }
    logger.info("Ingestion resumed", extra={"document_id": document_id, "resume_from": resume_from})
    await _run_graph(state)


async def _run_graph(initial_state: IngestionState) -> None:
    document_id, format = initial_state["document_id"], initial_state["format"]
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
            async with get_session_factory()() as session:
                await DocumentRepo(session).update_fields(
                    document_id, stage="error", ingest_resumes=0
                )
                await session.commit()


def _why_not_resumable(doc: DocumentModel) -> str | None:
    if doc.stage not in _RESUME_AT and doc.stage not in _RESTART_FROM_FILE:
        return _INTERRUPTED
    if not Path(doc.file_path).exists():
        return _INTERRUPTED
    if doc.ingest_resumes >= MAX_INGEST_RESUMES:
        return _INTERRUPTED_AGAIN
    return None


async def _fail(document_id: str, message: str) -> None:
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(
            document_id, stage="error", error_message=message, ingest_resumes=0
        )
        await session.commit()


async def _resume(doc: DocumentModel) -> None:
    deletion = get_document_deletion_service()
    entry = _RESUME_AT.get(doc.stage)
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(doc.id, ingest_resumes=doc.ingest_resumes + 1)
        if entry is None:
            await deletion.delete_derived_for_reparse(session, doc.id)
        await session.commit()
    if entry is None:
        await asyncio.to_thread(deletion.delete_lancedb_vectors, doc.id)
        work = run_ingestion(doc.id, doc.file_path, doc.format)
    else:
        work = resume_ingestion(doc.id, entry)
    get_ingestion_jobs().launch(doc.id, work)


async def resume_interrupted_ingestions() -> tuple[int, int]:
    """Resume, or fail, every ingestion the last process left unfinished: (resumed, failed)."""
    async with get_session_factory()() as session:
        unfinished = await DocumentRepo(session).unfinished()
    failed = 0
    for doc in unfinished:
        if message := _why_not_resumable(doc):
            await _fail(doc.id, message)
            failed += 1
        else:
            await _resume(doc)
    return len(unfinished) - failed, failed
