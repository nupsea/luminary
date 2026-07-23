"""parse_node and classify_node -- the front of the ingestion pipeline.

parse_node turns the raw file at `state['file_path']` into a structured
`parsed_document` dict via `DocumentParser`. Audio/video files skip
parsing here; transcribe_node handles them downstream.

classify_node assigns a `content_type` (book/conversation/notes/code/
tech_book/tech_article/...). It uses the heuristic in `_classify` plus
optional LLM reclassification for ambiguous large documents. If the
caller pre-supplied content_type, both heuristics and LLM are skipped.
"""

import logging
from pathlib import Path

from app.telemetry import trace_ingestion_node
from app.types import TECHNICAL_CONTENT_TYPES
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _classify,
    _parser,
    _persist_content_type,
    _persist_is_technical,
    _update_stage,
    resolve_technical_variant,
)

logger = logging.getLogger(__name__)


async def parse_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "parse", "doc_id": state["document_id"]})
    # Audio/video files: DocumentParser cannot handle them; transcribe_node takes over.
    # EPUB and other text-based formats are handled by DocumentParser below.
    if Path(state["file_path"]).suffix.lstrip(".").lower() in ("mp3", "m4a", "wav", "mp4"):
        return {**state, "parsed_document": None, "status": "classifying"}
    with trace_ingestion_node("parse", state):
        try:
            await _update_stage(state["document_id"], "parsing")
            fp = Path(state["file_path"])
            parsed = _parser.parse(fp, state["format"])
            sections = [
                {
                    "heading": s.heading,
                    "level": s.level,
                    "text": s.text,
                    "page_start": s.page_start,
                    "page_end": s.page_end,
                }
                for s in parsed.sections
            ]
            return {
                **state,
                "parsed_document": {
                    "title": parsed.title,
                    "format": parsed.format,
                    "pages": parsed.pages,
                    "word_count": parsed.word_count,
                    "sections": sections,
                    "raw_text": parsed.raw_text,
                },
                "status": "classifying",
            }
        except Exception as exc:
            logger.error("parse_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


async def classify_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "classify", "doc_id": state["document_id"]})
    # Fast-path: content_type was provided by the user — skip all heuristics and LLM.
    # Classification only runs for legacy paths where content_type is unknown.
    provided = state.get("content_type")
    if provided is not None:
        if provided == "technical":
            pd = state.get("parsed_document")
            resolved = resolve_technical_variant(pd["raw_text"]) if pd else "tech_article"
            await _persist_content_type(state["document_id"], resolved)
            await _persist_is_technical(state["document_id"], True)
            logger.info(
                "classify_node: resolved user-provided 'technical'",
                extra={"doc_id": state["document_id"], "content_type": resolved},
            )
            return {
                **state,
                "content_type": resolved,
                "is_technical": True,
                "status": "chunking",
            }
        if provided in ("audio", "video"):
            # Decided from the transcript in transcribe_node.
            logger.info(
                "classify_node: skipping (user-provided content_type)",
                extra={"doc_id": state["document_id"], "content_type": provided},
            )
            return {**state, "status": "chunking"}
        is_technical = provided in TECHNICAL_CONTENT_TYPES
        await _persist_is_technical(state["document_id"], is_technical)
        logger.info(
            "classify_node: skipping (user-provided content_type)",
            extra={"doc_id": state["document_id"], "content_type": provided},
        )
        return {**state, "is_technical": is_technical, "status": "chunking"}
    with trace_ingestion_node("classify", state):
        try:
            await _update_stage(state["document_id"], "classifying")
            pd = state["parsed_document"]
            if pd is None:
                return {**state, "content_type": "notes", "status": "chunking"}
            fp_obj = Path(state["file_path"])
            file_ext = fp_obj.suffix.lstrip(".")
            filename = fp_obj.name
            content_type = _classify(
                pd["raw_text"], pd["sections"], pd["word_count"], file_ext, filename
            )

            # LLM reclassification: heuristic result is uncertain for large documents.
            # 'notes' on a long doc may be book/paper; 'conversation' on a very long doc
            # (>20k words) is likely misclassified — epics/plays have speaker patterns too.
            needs_llm = (content_type == "notes" and pd["word_count"] > 5000) or (
                content_type == "conversation" and pd["word_count"] > 20000
            )
            if needs_llm:
                try:
                    from app.services.llm import get_llm_service  # noqa: PLC0415

                    snippet = pd["raw_text"][:2000]
                    prompt = (
                        "Classify this document as exactly one of: "
                        "paper, book, conversation, notes, code, tech_book, tech_article.\n"
                        f"Document snippet (first 2000 chars):\n{snippet}\n\n"
                        "Reply with exactly one word from the list above."
                    )
                    llm_result = await get_llm_service().generate(prompt, background=True)
                    llm_type = str(llm_result).strip().lower().split()[0]
                    _valid_types = {
                        "paper",
                        "book",
                        "conversation",
                        "notes",
                        "code",
                        "tech_book",
                        "tech_article",
                    }
                    if llm_type in _valid_types:
                        content_type = llm_type
                        logger.info(
                            "LLM reclassified document",
                            extra={
                                "doc_id": state["document_id"],
                                "content_type": content_type,
                            },
                        )
                except Exception as exc:
                    # Expected when Ollama is offline — log the one-line cause only,
                    # not the full traceback (ConnectionRefusedError is not a bug).
                    logger.warning(
                        "LLM reclassification failed, keeping heuristic result: %s",
                        type(exc).__name__,
                    )

            # Media documents are decided in transcribe_node instead — their text
            # does not exist yet at this point.
            is_technical = content_type in TECHNICAL_CONTENT_TYPES
            await _persist_is_technical(state["document_id"], is_technical)

            logger.info(
                "Classified document",
                extra={
                    "doc_id": state["document_id"],
                    "content_type": content_type,
                    "is_technical": is_technical,
                },
            )
            return {
                **state,
                "content_type": content_type,
                "is_technical": is_technical,
                "status": "chunking",
            }
        except Exception as exc:
            logger.error("classify_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}
