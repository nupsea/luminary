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

from app.runtime.chat_nodes.comparative import (
    _decompose_comparison,  # noqa: F401  re-exported for back-compat
    _resolve_side_to_docs,  # noqa: F401  re-exported for back-compat
    comparative_node,  # noqa: F401  re-exported for back-compat
)
from app.runtime.chat_nodes.confidence import (
    _route_after_confidence_gate,
    augment_node,
    confidence_gate_node,
    web_augment_node,
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

# confidence_gate_node + _route_after_confidence_gate + augment_node +
# web_augment_node live in chat_nodes/confidence.py and are re-exported
# above for back-compat.


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
