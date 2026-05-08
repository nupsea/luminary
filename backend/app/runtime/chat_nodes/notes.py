"""notes_node and notes_gap_node.

notes_node (intent='notes'): search user notes via NoteSearchService,
optionally enrich top-3 with Kuzu entity names, return as
section_context for synthesize_node.

notes_gap_node (intent='notes_gap'): detect gaps between user notes
and a single document via GapDetectorService, return a __card__
sentinel that stream_answer() emits as a structured SSE card.
Bypasses synthesize/confidence nodes.
"""

import json
import logging

from app.services.llm import LLMUnavailableError
from app.types import ChatState

logger = logging.getLogger(__name__)


async def notes_node(state: ChatState) -> dict:
    """Search user notes via NoteSearchService and format context for synthesize_node."""
    q = state.get("rewritten_question") or state["question"]
    logger.info("notes_node: query=%r", q[:80])

    from app.services.note_search import get_note_search_service  # noqa: PLC0415

    try:
        results = await get_note_search_service().search(q, k=5)
    except Exception:
        logger.warning("notes_node: search failed", exc_info=True)
        results = []

    if not results:
        logger.info("notes_node: no note results for query=%r", q[:50])
        return {"chunks": [], "section_context": None}

    # Enrich top-3 notes with Kuzu entity names (S163)
    note_lines = []
    for i, r in enumerate(results):
        line = "[From your notes] " + r.content
        if i < 3:
            try:
                from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

                entities = await get_note_graph_service().get_entities_for_note(r.note_id)
                if entities:
                    entity_names = ", ".join(e["name"] for e in entities[:5])
                    line += f" [Entities: {entity_names}]"
            except Exception:
                pass  # Entity enrichment is non-blocking
        note_lines.append(line)

    section_context = "\n\n".join(note_lines)
    logger.info("notes_node: found %d notes, ctx_len=%d", len(results), len(section_context))
    return {"chunks": [], "section_context": section_context}


async def notes_gap_node(state: ChatState) -> dict:
    """Detect gaps between the user's notes and a book document.

    Fetches notes for doc_ids[0], calls GapDetectorService.detect_gaps, and
    sets state['answer'] to the __card__ sentinel string so stream_answer()
    emits a structured card SSE event instead of streaming text tokens.

    All error cases (no document, no notes, Ollama offline) return a __card__
    with an 'error' field -- never raise to the SSE stream.

    Routes directly to END (bypasses synthesize/confidence nodes -- card answers
    are fully formed by this node and have no confidence to retry).
    """
    logger.info("notes_gap_node: starting gap detection")
    doc_ids = state.get("doc_ids") or []
    document_id = doc_ids[0] if len(doc_ids) == 1 else None

    if not document_id:
        logger.info("notes_gap_node: no single document_id in state -- returning error card")
        card = {
            "type": "gap_result",
            "error": (
                "Please select a specific document to compare against your notes. "
                "Switch to 'This document' scope and choose a book."
            ),
            "gaps": [],
            "covered": [],
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    # S197: auto-fetch notes from the document's auto-collection
    auto_collection_id: str | None = None
    try:
        from sqlalchemy import select  # noqa: PLC0415

        from app.database import get_session_factory  # noqa: PLC0415
        from app.models import CollectionMemberModel, CollectionModel  # noqa: PLC0415

        async with get_session_factory()() as session:
            # Step 1: find auto-collection for this document
            coll_row = (
                await session.execute(
                    select(CollectionModel.id).where(
                        CollectionModel.auto_document_id == document_id
                    )
                )
            ).first()
            if coll_row:
                auto_collection_id = coll_row[0]
                # Step 2: fetch note IDs from collection members
                member_rows = (
                    await session.execute(
                        select(CollectionMemberModel.member_id).where(
                            CollectionMemberModel.collection_id == auto_collection_id,
                            CollectionMemberModel.member_type == "note",
                        )
                    )
                ).fetchall()
                note_ids = [r[0] for r in member_rows]
            else:
                note_ids = []
    except Exception:
        logger.warning("notes_gap_node: note fetch failed", exc_info=True)
        card = {
            "type": "gap_result",
            "error": "Could not fetch notes. Please try again.",
            "gaps": [],
            "covered": [],
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    if not note_ids:
        logger.info("notes_gap_node: no notes for document %s -- returning card", document_id)
        card = {
            "type": "gap_result",
            "error": (
                "No notes found for this document. "
                "Start taking notes in the reader to use gap analysis."
            ),
            "gaps": [],
            "covered": [],
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    if len(note_ids) < 3:
        logger.info(
            "notes_gap_node: only %d notes for document %s -- suggesting more",
            len(note_ids),
            document_id,
        )
        card = {
            "type": "gap_result",
            "error": (
                f"You have only {len(note_ids)} note(s) for this document. "
                "Take a few more notes while reading, then try gap analysis again."
            ),
            "gaps": [],
            "covered": [],
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    try:
        from app.services.gap_detector import get_gap_detector  # noqa: PLC0415

        report = await get_gap_detector().detect_gaps(note_ids, document_id)
        card: dict = {
            "type": "gap_result",
            "gaps": report["gaps"],
            "covered": report["covered"],
            "query_used": report["query_used"],
            "document_id": document_id,
        }
        if auto_collection_id:
            card["auto_collection_id"] = auto_collection_id
        logger.info(
            "notes_gap_node: gaps=%d covered=%d", len(report["gaps"]), len(report["covered"])
        )
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    except Exception as exc:
        if isinstance(exc, LLMUnavailableError):
            error_msg = "LLM unavailable. Check Settings — if using Ollama, run: ollama serve"
        else:
            error_msg = "Gap analysis failed. Please try again."
        logger.warning("notes_gap_node: detect_gaps failed: %s", exc, exc_info=True)
        card = {
            "type": "gap_result",
            "error": error_msg,
            "gaps": [],
            "covered": [],
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}
