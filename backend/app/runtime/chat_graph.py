"""LangGraph StateGraph for the V2 agentic chat router.

S77: skeleton with stub strategy nodes.
S78: real implementations for all strategy nodes.
S81: confidence-adaptive retry with augment_node + confidence_gate_node.

Graph flow:
    classify_node
      → [conditional by intent]
        → summary_node    → [conditional fallthrough] → synthesize_node
        → graph_node      → [conditional fallthrough] → synthesize_node
        → comparative_node → synthesize_node
        → search_node      → synthesize_node
      → confidence_gate_node
        → (high|medium confidence, OR retry_attempted=True) → END
        → (low confidence, retry_attempted=False) → augment_node
          → synthesize_node → confidence_gate_node → END

Strategy nodes:
    summary_node     — intent='summary': fetch executive summary from DB
    graph_node       — intent='relational': Kuzu entity traversal + hybrid retrieval
    comparative_node — intent='comparative': dual retrieval with interleaving
    search_node      — intent='factual'|'exploratory': hybrid retrieval + section augmentation
"""

import logging

from langgraph.graph import END, StateGraph

from app.runtime.chat_nodes._shared import (
    _chunk_to_dict,
)
from app.runtime.chat_nodes.comparative import (
    _decompose_comparison,  # noqa: F401  re-exported for back-compat
    _resolve_side_to_docs,  # noqa: F401  re-exported for back-compat
    comparative_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.graph import (
    _extract_entities_from_question,  # noqa: F401  re-exported for back-compat
    _query_kuzu_for_entity,  # noqa: F401  re-exported for back-compat
    graph_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.notes import (
    notes_gap_node,  # noqa: F401  re-exported for back-compat
    notes_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.search import (
    _fetch_neighbor_chunks,  # noqa: F401  re-exported for back-compat
    _fetch_section_summaries,  # noqa: F401  re-exported for back-compat
    search_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.socratic import (
    _TEACH_BACK_SYSTEM,  # noqa: F401  re-exported for back-compat
    socratic_node,  # noqa: F401  re-exported for back-compat
    teach_back_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.summary import (
    _fetch_all_doc_executive_summaries,  # noqa: F401  re-exported for back-compat
    _fetch_library_executive_summary,  # noqa: F401  re-exported for back-compat
    _fetch_single_doc_executive_summary,  # noqa: F401  re-exported for back-compat
    _generate_library_summary_task,  # noqa: F401  re-exported for back-compat
    summary_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.synthesize import (
    _fetch_contradiction_context,  # noqa: F401  re-exported for back-compat
    _fetch_doc_titles_for_chunks,  # noqa: F401  re-exported for back-compat
    _fetch_section_ids_and_pages_for_chunks,  # noqa: F401  re-exported for back-compat
    synthesize_node,  # noqa: F401  re-exported for back-compat
)
from app.services.intent import _llm_classify_fallback, classify_intent_heuristic
from app.services.qa import (
    _maybe_rewrite_query,
)
from app.services.retriever import get_retriever
from app.types import ChatState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# classify_node — intent detection + query rewriting
# ---------------------------------------------------------------------------


async def classify_node(state: ChatState) -> dict:
    """Detect intent (heuristic + optional LLM fallback) and rewrite vague queries."""
    question = state["question"]
    scope = state.get("scope", "all")
    doc_ids = state.get("doc_ids") or []

    logger.info(
        "chat: question=%r scope=%s docs=%d",
        question[:80],
        scope,
        len(doc_ids),
    )

    intent, confidence = classify_intent_heuristic(question)
    source = "heuristic"

    if confidence < 0.9:
        intent = await _llm_classify_fallback(question, scope=scope, default=intent)
        source = "llm"

    logger.info(
        "classify_node: intent=%s confidence=%.2f source=%s",
        intent,
        confidence,
        source,
    )

    # Query rewriting via Kuzu entities — non-fatal
    # Supply last user turn from history as prior_context so vague follow-ups
    # like "Are there no similarities?" can be grounded without a Kuzu lookup.
    effective_doc_ids = doc_ids if state.get("scope") == "single" else None
    history = state.get("conversation_history") or []
    prior_context: str | None = None
    for msg in reversed(history):
        if isinstance(msg, dict) and msg.get("role") == "user":
            prior_context = msg.get("content")
            break
    try:
        rewritten = await _maybe_rewrite_query(question, effective_doc_ids, prior_context)
        if rewritten != question:
            logger.info("classify_node: query rewritten → %r", rewritten[:80])
    except Exception:
        rewritten = question

    _intent_to_strategy = {
        "summary": "summary_node",
        "relational": "graph_node",
        "comparative": "comparative_node",
        "notes": "notes_node",
        "socratic": "socratic_node",
        "teach_back": "teach_back_node",
    }
    primary_strategy = _intent_to_strategy.get(intent, "search_node")

    return {
        "intent": intent,
        "rewritten_question": rewritten,
        "primary_strategy": primary_strategy,
    }


# ---------------------------------------------------------------------------
# route_node — conditional edge function after classify_node
# ---------------------------------------------------------------------------


def route_node(state: ChatState) -> str:
    """Return the next node name based on detected intent and scope.

    Routing rules:
      summary    → summary_node (fetch cached executive summaries)
      relational → graph_node   (Kuzu entity traversal)
      comparative → comparative_node (dual retrieval)
      exploratory + scope=all → summary_node (broad cross-doc questions need
                                 per-doc summary synthesis, not biased chunk retrieval)
      factual / exploratory + scope=single → search_node (specific lookup)
    """
    intent = state.get("intent") or "factual"
    scope = state.get("scope", "all")
    if intent == "teach_back":
        node = "teach_back_node"
    elif intent == "socratic":
        node = "socratic_node"
    elif intent == "notes_gap":
        node = "notes_gap_node"
    elif intent == "notes":
        node = "notes_node"
    elif intent == "summary":
        node = "summary_node"
    elif intent == "relational":
        node = "graph_node"
    elif intent == "comparative":
        node = "comparative_node"
    elif intent == "exploratory" and scope == "all":
        node = "summary_node"
    else:
        node = "search_node"
    logger.info("route_node: intent=%s scope=%s → %s", intent, scope, node)
    return node


def _route_after_strategy(state: ChatState) -> str:
    """Conditional edge after summary_node / graph_node.

    If the node could not satisfy the query (sets intent='factual' as a fallthrough
    signal), re-route to search_node.  Otherwise proceed to synthesize_node.
    """
    if state.get("intent") == "factual":
        return "search_node"
    return "synthesize_node"


# summary_node lives in chat_nodes/summary.py and is re-exported above
# for back-compat with `from app.runtime.chat_graph import summary_node`.


# graph_node lives in chat_nodes/graph.py and is re-exported above
# for back-compat with `from app.runtime.chat_graph import graph_node`.


# comparative_node lives in chat_nodes/comparative.py and is re-exported
# above for back-compat.


# search_node lives in chat_nodes/search.py and is re-exported above
# for back-compat.


# notes_node + notes_gap_node live in chat_nodes/notes.py and are
# re-exported above for back-compat.


# socratic_node + teach_back_node live in chat_nodes/socratic.py and are
# re-exported above for back-compat.


# synthesize_node lives in chat_nodes/synthesize.py and is re-exported
# above for back-compat. augment_node calls it through the re-exported
# name so test patches on `chat_graph.synthesize_node` keep working.


# ---------------------------------------------------------------------------
# confidence_gate_node + augment_node (S81)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# web_augment_node — fetch web snippets for low-confidence answers (S142)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Graph construction + singleton
# ---------------------------------------------------------------------------


def build_chat_graph() -> StateGraph:
    """Build the V2 chat StateGraph."""
    global _compiled_graph  # noqa: PLW0603
    _compiled_graph = None  # Reset singleton so tests can rebuild the graph

    g: StateGraph = StateGraph(ChatState)  # type: ignore[type-var]

    g.add_node("classify_node", classify_node)
    g.add_node("notes_node", notes_node)
    g.add_node("notes_gap_node", notes_gap_node)
    g.add_node("socratic_node", socratic_node)
    g.add_node("teach_back_node", teach_back_node)
    g.add_node("summary_node", summary_node)
    g.add_node("search_node", search_node)
    g.add_node("graph_node", graph_node)
    g.add_node("comparative_node", comparative_node)
    g.add_node("synthesize_node", synthesize_node)
    g.add_node("confidence_gate_node", confidence_gate_node)
    g.add_node("augment_node", augment_node)
    g.add_node("web_augment_node", web_augment_node)

    g.set_entry_point("classify_node")

    g.add_conditional_edges(
        "classify_node",
        route_node,
        {
            "teach_back_node": "teach_back_node",
            "socratic_node": "socratic_node",
            "notes_gap_node": "notes_gap_node",
            "notes_node": "notes_node",
            "summary_node": "summary_node",
            "graph_node": "graph_node",
            "comparative_node": "comparative_node",
            "search_node": "search_node",
        },
    )

    # summary_node and graph_node can fall through to search_node
    for fallthrough_node in ("summary_node", "graph_node"):
        g.add_conditional_edges(
            fallthrough_node,
            _route_after_strategy,
            {
                "search_node": "search_node",
                "synthesize_node": "synthesize_node",
            },
        )

    # card nodes route to END -- card answers skip synthesize/confidence retry
    g.add_edge("teach_back_node", END)
    g.add_edge("socratic_node", END)
    g.add_edge("notes_gap_node", END)
    g.add_edge("notes_node", "synthesize_node")
    g.add_edge("comparative_node", "synthesize_node")
    g.add_edge("search_node", "synthesize_node")

    # synthesize_node → confidence_gate_node → (END | augment_node)
    g.add_edge("synthesize_node", "confidence_gate_node")
    g.add_conditional_edges(
        "confidence_gate_node",
        _route_after_confidence_gate,
        {
            "augment_node": "augment_node",
            "web_augment_node": "web_augment_node",
            END: END,
        },
    )
    # Retry paths:
    #   augment_node → synthesize_node → confidence_gate_node → END
    #   web_augment_node → synthesize_node → confidence_gate_node → END
    g.add_edge("augment_node", "synthesize_node")
    g.add_edge("web_augment_node", "synthesize_node")

    return g


_compiled_graph = None


def get_chat_graph():
    """Return the compiled chat graph singleton."""
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        _compiled_graph = build_chat_graph().compile()
    return _compiled_graph
