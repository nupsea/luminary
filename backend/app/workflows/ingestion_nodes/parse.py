"""parse_node and classify_node -- the front of the ingestion pipeline.

parse_node turns the raw file at `state['file_path']` into a structured
`parsed_document` dict via `DocumentParser`. Audio/video files skip
parsing here; transcribe_node handles them downstream.

classify_node measures the facets -- form from structure, domain and register
from the text -- and lays a kind the reader chose over them (#223). Media is
measured from its transcript, in transcribe_node.
"""

import asyncio
import logging
from pathlib import Path

from app.database import get_session_factory
from app.repos.document_kind_repo import DocumentKindRepo
from app.repos.document_repo import DocumentRepo
from app.services.content_classifier import classify_form
from app.telemetry import trace_ingestion_node
from app.types import MEDIA_FORMATS, register_for_form
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _parser,
    _persist_classification,
    _persist_extraction_report,
    _persist_structure_type,
    _update_stage,
    as_domain,
    detect_register,
    measure_domain,
    reader_facets,
)

logger = logging.getLogger(__name__)


async def parse_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "parse", "doc_id": state["document_id"]})
    # Audio/video files: DocumentParser cannot handle them; transcribe_node takes over.
    # EPUB and other text-based formats are handled by DocumentParser below.
    if Path(state["file_path"]).suffix.lstrip(".").lower() in MEDIA_FORMATS:
        return {**state, "parsed_document": None, "status": "classifying"}
    with trace_ingestion_node("parse", state):
        try:
            await _update_stage(state["document_id"], "parsing")
            fp = Path(state["file_path"])
            # Off the event loop: parsing is one uninterrupted CPU call with no
            # await inside it, so on the single worker it stalls every other
            # request for its whole duration -- measured 44.9s on a 23MB PDF,
            # during which the app serves neither the API nor its own SPA
            # chunks, and the UI cannot navigate (I-2).
            parsed = await asyncio.to_thread(_parser.parse, fp, state["format"])
            sections = [
                {
                    "heading": s.heading,
                    "level": s.level,
                    "text": s.text,
                    "page_start": s.page_start,
                    "page_end": s.page_end,
                    "page_breaks": s.page_breaks,
                }
                for s in parsed.sections
            ]
            # Persisted here, beside the parse that discovers them.
            if parsed.structure_type:
                await _persist_structure_type(state["document_id"], parsed.structure_type)
            if parsed.extraction_report is not None:
                await _persist_extraction_report(state["document_id"], parsed.extraction_report)
            return {
                **state,
                "parsed_document": {
                    "title": parsed.title,
                    "format": parsed.format,
                    "pages": parsed.pages,
                    "word_count": parsed.word_count,
                    "sections": sections,
                    "raw_text": parsed.raw_text,
                    # Sheet -> printed page, for PDFs that number front matter
                    # separately. Empty when counting sheets is already right.
                    "page_labels": parsed.page_labels,
                },
                "structure_type": parsed.structure_type,
                "status": "classifying",
            }
        except Exception as exc:
            logger.exception("parse_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


def _measure_form(state: IngestionState) -> str:
    pd = state["parsed_document"]
    fp = Path(state["file_path"])
    return classify_form(
        pd["raw_text"], pd["sections"], pd["word_count"], fp.suffix.lstrip("."), fp.name
    )


async def _measure_register(form: str | None, pd: dict | None) -> str | None:
    # A paper reports and a manual instructs, so the shape settles it and the
    # probe would spend ~2.6s on a known answer. Combining the two probes into
    # one call was measured instead and is worse on both axes and 0.84x the
    # speed -- the cost is prompt tokens, not call overhead.
    settled = register_for_form(form) if form else None
    if settled is not None:
        return settled
    raw_text = (pd or {}).get("raw_text") or ""
    return await detect_register(raw_text) if raw_text.strip() else None


async def _measure_facets(form: str, pd: dict) -> tuple[str | None, str | None]:
    """Read the domain and the register from the document, in one pass.

    Both are asked of the text, because the shape carries neither: a novel and a
    deep-learning textbook are both prose, and nothing about a shape says whether
    a work tells or explains. None when a probe cannot answer, never "general";
    `remeasure_domain` retries.
    """
    domain = as_domain(await measure_domain(form, pd.get("raw_text") or ""))
    return domain, await _measure_register(form, pd)


async def classify_node(state: IngestionState) -> IngestionState:
    result = await _measure_classification(state)
    if result.get("status") == "error":
        return result
    async with get_session_factory()() as session:
        if state.get("kind"):
            chosen = await DocumentKindRepo(session).choose(state["document_id"], state["kind"])
        else:
            chosen = await reader_facets(DocumentRepo(session), state["document_id"])
    if chosen is None:
        return result
    # Chunking follows the kind the reader chose, which persistence kept on the row.
    form, domain = chosen
    return {**result, "form": form, "domain": domain}


async def _measure_classification(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "classify", "doc_id": state["document_id"]})
    pd = state.get("parsed_document")
    if pd is None:
        # Media: no text until transcribe_node, which measures it from the transcript.
        return {**state, "status": "chunking"}
    # Before the classify probes, which queue behind other LLM work (#142).
    await _update_stage(state["document_id"], "classifying")
    with trace_ingestion_node("classify", state):
        try:
            # Measured from structure, never from a type: the old type map reached
            # `reference` only through `tech_book`, so a non-technical manual never could.
            form = _measure_form(state)
            domain, register = await _measure_facets(form, pd)
            # The classified facets reach the row, not just the state: the library,
            # filters and every later read come from the row.
            await _persist_classification(state["document_id"], form, domain, register)
            logger.info(
                "Classified document",
                extra={"doc_id": state["document_id"], "form": form, "domain": domain},
            )
            return {**state, "form": form, "domain": domain, "status": "chunking"}
        except Exception as exc:
            logger.exception("classify_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}
