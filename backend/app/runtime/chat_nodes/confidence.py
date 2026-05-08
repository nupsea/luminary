"""confidence_gate_node + augment_node + web_augment_node (S81, S142).

confidence_gate_node is a no-op data node; the routing decision lives
in `_route_after_confidence_gate`. The retry loop is single-shot:
`retry_attempted` guards both web and local augmentation paths.

augment_node fans out a complementary retrieval strategy chosen from
`primary_strategy`, *appends* (never replaces) new context, and sets
`transparency_augmented=True` so synthesize_node flags the SSE event.

web_augment_node is the optional first leg of the retry loop -- only
fires when web is enabled, confidence is low, and the per-conversation
rate limit (3 calls) has not been hit. Snippets are stored in state
only; they're never persisted to disk (privacy invariant).
"""

import logging

from langgraph.graph import END

from app.runtime.chat_nodes._shared import _chunk_to_dict
from app.runtime.chat_nodes.graph import (
    _extract_entities_from_question,
    _query_kuzu_for_entity,
)
from app.services.retriever import get_retriever
from app.types import ChatState

logger = logging.getLogger(__name__)


async def confidence_gate_node(state: ChatState) -> dict:
    """No-op node; routing decision is made by _route_after_confidence_gate."""
    confidence = state.get("confidence", "low")
    retry_attempted = state.get("retry_attempted", False)
    logger.info(
        "confidence_gate_node: confidence=%s retry_attempted=%s",
        confidence,
        retry_attempted,
    )
    return {}


def _route_after_confidence_gate(state: ChatState) -> str:
    """Conditional edge after confidence_gate_node.

    Routes to END unless confidence is 'low' AND this is the first attempt.
    When web_enabled=True and within rate limit, routes to web_augment_node first.
    Guarantees at most 1 retry loop (retry_attempted guards both web and local augment).
    """
    confidence = state.get("confidence", "low")
    retry_attempted = state.get("retry_attempted", False)
    if confidence == "low" and not retry_attempted:
        web_enabled = state.get("web_enabled", False)
        web_calls_used = state.get("web_calls_used", 0)
        if web_enabled and web_calls_used < 3:
            logger.info(
                "confidence_gate_node: low confidence + web_enabled -- routing to web_augment_node"
            )
            return "web_augment_node"
        logger.info("confidence_gate_node: low confidence, triggering augment retry")
        return "augment_node"
    logger.info("confidence_gate_node: confidence=%s -- routing to END", confidence)
    return END


async def augment_node(state: ChatState) -> dict:
    """Augment context with a complementary strategy when confidence is low.

    Selects the complementary strategy based on primary_strategy:
      search_node / factual / exploratory → Kuzu entity graph lines → section_context
      graph_node (relational)             → hybrid search k=15 → chunks
      summary_node                        → hybrid search k=10 → chunks
      comparative_node                    → hybrid search k=10, no doc filter → chunks
      notes_node                          → broader note search k=10 → section_context

    APPENDS to existing chunks/section_context; pack_context() deduplicates.
    Non-fatal: all errors caught and logged; returns {retry_attempted: True}.
    """
    primary = state.get("primary_strategy") or "search_node"
    question = state.get("rewritten_question") or state["question"]
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None
    logger.info("augment_node: low confidence — augmenting context (primary=%s)", primary)

    existing_chunks: list[dict] = list(state.get("chunks") or [])
    existing_section_context: str = state.get("section_context") or ""

    new_chunks: list[dict] = []
    new_section_lines: list[str] = []

    try:
        if primary in ("search_node", "factual", "exploratory"):
            # Complementary: Kuzu entity graph relationships
            entity_names = _extract_entities_from_question(question)
            try:
                from app.services.graph import get_graph_service  # noqa: PLC0415

                conn = get_graph_service()._conn
                for name in entity_names[:5]:
                    new_section_lines.extend(_query_kuzu_for_entity(conn, name))
            except Exception:
                logger.warning("augment_node: Kuzu query failed", exc_info=True)

        elif primary == "graph_node":
            # Complementary: broader hybrid search k=15
            retriever = get_retriever()
            chunks = await retriever.retrieve(question, effective_doc_ids, k=15)
            new_chunks = [_chunk_to_dict(c) for c in chunks]

        elif primary == "summary_node":
            # Complementary: hybrid search k=10
            retriever = get_retriever()
            chunks = await retriever.retrieve(question, effective_doc_ids, k=10)
            new_chunks = [_chunk_to_dict(c) for c in chunks]

        elif primary == "comparative_node":
            # Complementary: hybrid search k=10, no doc_id filter
            retriever = get_retriever()
            chunks = await retriever.retrieve(question, None, k=10)
            new_chunks = [_chunk_to_dict(c) for c in chunks]

        elif primary == "notes_node":
            # Complementary: broader note search k=10
            from app.services.note_search import get_note_search_service  # noqa: PLC0415

            try:
                extra_results = await get_note_search_service().search(question, k=10)
                for r in extra_results:
                    new_section_lines.append("[From your notes] " + r.content)
            except Exception:
                logger.warning("augment_node: note search failed", exc_info=True)

    except Exception:
        logger.warning("augment_node: augmentation failed", exc_info=True)
        return {"retry_attempted": True, "transparency_augmented": True}

    # Append new context; pack_context() handles deduplication
    combined_chunks = existing_chunks + new_chunks

    combined_section_context = existing_section_context
    if new_section_lines:
        supplement = "Knowledge graph supplement:\n" + "\n".join(new_section_lines)
        if combined_section_context:
            combined_section_context = combined_section_context + "\n\n" + supplement
        else:
            combined_section_context = supplement

    logger.info(
        "augment_node: added %d chunks + %d graph lines (total chunks now %d)",
        len(new_chunks),
        len(new_section_lines),
        len(combined_chunks),
    )
    return {
        "chunks": combined_chunks,
        "section_context": combined_section_context,
        "retry_attempted": True,
        "transparency_augmented": True,  # S158: signals synthesize_node to set augmented=True
    }


async def web_augment_node(state: ChatState) -> dict:
    """Fetch web snippets to supplement low-confidence local answers.

    Fires only when:
      - state['web_enabled'] is True
      - state['confidence'] is 'low' (string value, not float)
      - state['web_calls_used'] < 3 (per-conversation rate limit)

    Returns {} (no-op) when any condition is False.
    Appends snippets to state['web_snippets'], increments web_calls_used.
    Sets retry_attempted=True so confidence_gate_node routes to END on next pass.
    Web snippets are NOT written to DB (privacy invariant).
    """
    web_enabled = state.get("web_enabled", False)
    confidence = state.get("confidence", "high")
    web_calls_used = state.get("web_calls_used", 0)

    if not web_enabled:
        logger.info("web_augment_node: web_enabled=False -- skipping")
        return {}

    if confidence != "low":
        logger.info("web_augment_node: confidence=%s -- skipping (only fires on low)", confidence)
        return {}

    if web_calls_used >= 3:
        logger.info(
            "web_augment_node: rate limit reached (%d/3) -- local-only fallback", web_calls_used
        )
        return {}

    question = state.get("rewritten_question") or state["question"]
    logger.info("web_augment_node: fetching web snippets for query=%r", question[:60])

    from app.services.web_searcher import get_web_searcher  # noqa: PLC0415

    snippets: list[dict] = []
    try:
        results = await get_web_searcher().search(question, k=3)
        snippets = [dict(s) for s in results]
    except Exception:
        logger.warning("web_augment_node: web search failed", exc_info=True)
        snippets = []

    if not snippets:
        logger.info("web_augment_node: no web results returned")
        # Still set retry_attempted=True to prevent a second augment loop
        return {"web_calls_used": web_calls_used + 1, "retry_attempted": True}

    # Format snippets as labeled section_context entries
    existing_section_context = state.get("section_context") or ""
    web_lines = [f"[Web: {s['domain']}]\nTitle: {s['title']}\n{s['content']}" for s in snippets]
    web_context = "\n\n".join(web_lines)

    if existing_section_context:
        combined = existing_section_context + "\n\n---\n\n" + web_context
    else:
        combined = web_context

    existing_snippets = list(state.get("web_snippets") or [])
    logger.info(
        "web_augment_node: added %d web snippets (total web_calls_used=%d)",
        len(snippets),
        web_calls_used + 1,
    )
    return {
        "section_context": combined,
        "web_snippets": existing_snippets + snippets,
        "web_calls_used": web_calls_used + 1,
        "retry_attempted": True,  # prevents a second confidence-gate retry loop
    }
