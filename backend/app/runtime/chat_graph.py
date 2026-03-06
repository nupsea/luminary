"""LangGraph StateGraph for the V2 agentic chat router (S77 skeleton).

Graph flow:
    classify_node → [conditional edge by intent] → strategy_node → synthesize_node → END

Strategy nodes (STUBS for S78 — will be replaced with real implementations):
    summary_node    — intent='summary'
    graph_node      — intent='relational'
    comparative_node — intent='comparative'
    search_node     — intent='factual' or 'exploratory'

synthesize_node (STUB for S79): calls LLM with chunks, writes answer/citations/confidence.
If a strategy node already set a non-empty answer, synthesize_node passes through.

The graph is compiled once at module load via get_chat_graph() and reused.
"""

import logging

import litellm
from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel
from app.services.intent import _llm_classify_fallback, classify_intent_heuristic
from app.services.llm import get_llm_service
from app.services.qa import (
    NOT_FOUND_SENTINEL,
    QA_SYSTEM_PROMPT,
    _build_context,
    _enrich_citation_titles,
    _maybe_rewrite_query,
    _should_use_summary,
    _split_response,
)
from app.services.retriever import get_retriever
from app.types import ChatState, ScoredChunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# classify_node — intent detection + query rewriting
# ---------------------------------------------------------------------------


async def classify_node(state: ChatState) -> dict:
    """Detect intent (heuristic + optional LLM fallback) and rewrite vague queries."""
    question = state["question"]
    intent, confidence = classify_intent_heuristic(question)

    if confidence < 0.7:
        intent = await _llm_classify_fallback(question, default=intent)

    # Query rewriting via Kuzu entities — non-fatal
    doc_ids = state.get("doc_ids") or []
    effective_doc_ids = doc_ids if state.get("scope") == "single" else None
    try:
        rewritten = await _maybe_rewrite_query(question, effective_doc_ids)
    except Exception:
        rewritten = question

    logger.debug(
        "classify_node: intent=%s confidence=%.2f", intent, confidence
    )
    return {"intent": intent, "rewritten_question": rewritten}


# ---------------------------------------------------------------------------
# route_node — conditional edge function (not a graph node)
# ---------------------------------------------------------------------------


def route_node(state: ChatState) -> str:
    """Return the next node name based on detected intent."""
    intent = state.get("intent") or "factual"
    if intent == "summary":
        return "summary_node"
    if intent == "relational":
        return "graph_node"
    if intent == "comparative":
        return "comparative_node"
    # factual or exploratory
    return "search_node"


# ---------------------------------------------------------------------------
# Strategy node stubs (S78 will replace with real implementations)
# ---------------------------------------------------------------------------


async def summary_node(state: ChatState) -> dict:
    """STUB for S78 — summary retrieval; real implementation in S78."""
    return {"answer": "[summary_node stub]", "confidence": "high"}


async def graph_node(state: ChatState) -> dict:
    """STUB for S78 — graph traversal for relational queries."""
    return {"answer": "[graph_node stub]"}


async def comparative_node(state: ChatState) -> dict:
    """STUB for S78 — comparative analysis across sources."""
    return {"answer": "[comparative_node stub]"}


async def search_node(state: ChatState) -> dict:
    """STUB for S78 — hybrid retrieval; writes chunks to state."""
    try:
        retriever = get_retriever()
        q = state.get("rewritten_question") or state["question"]
        doc_ids = state.get("doc_ids") or []
        effective_doc_ids = doc_ids if state.get("scope") == "single" else None
        chunks: list[ScoredChunk] = await retriever.retrieve(q, effective_doc_ids, k=10)
        chunks_dicts = [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "text": c.text,
                "section_heading": c.section_heading,
                "page": c.page,
                "score": c.score,
                "source": c.source,
            }
            for c in chunks
        ]
    except Exception:
        logger.warning("search_node: retrieval failed", exc_info=True)
        chunks_dicts = []

    return {"chunks": chunks_dicts}


# ---------------------------------------------------------------------------
# synthesize_node (STUB for S79 — copies stream_answer LLM logic)
# ---------------------------------------------------------------------------


async def _fetch_doc_titles_for_chunks(chunks_dicts: list[dict]) -> dict[str, str]:
    doc_ids = list({c["document_id"] for c in chunks_dicts if c.get("document_id")})
    if not doc_ids:
        return {}
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(DocumentModel.id, DocumentModel.title).where(
                DocumentModel.id.in_(doc_ids)
            )
        )
        return {row.id: row.title for row in rows}


async def synthesize_node(state: ChatState) -> dict:
    """STUB for S79 — calls LLM with chunk context, writes answer/citations/confidence.

    Pass-through: if a strategy node already set a non-empty answer (e.g. summary_node
    stub), this node returns {} and leaves the answer unchanged.

    No-context: if chunks list is empty, returns {"not_found": True} without LLM call.

    LLM errors are re-raised so stream_answer() can surface them with the correct
    SSE error event format.
    """
    existing_answer = state.get("answer", "")
    if existing_answer:
        # Strategy node already produced an answer — pass through
        return {}

    chunks_dicts = state.get("chunks") or []
    question = state["question"]
    model = state.get("model")
    scope = state.get("scope", "all")

    if not chunks_dicts:
        return {"not_found": True}

    # Reconstruct ScoredChunk objects for _build_context / _enrich_citation_titles
    scored_chunks = [
        ScoredChunk(
            chunk_id=c.get("chunk_id", ""),
            document_id=c.get("document_id", ""),
            text=c.get("text", ""),
            section_heading=c.get("section_heading", ""),
            page=c.get("page", 0),
            score=c.get("score", 0.0),
            source=c.get("source", "vector"),  # type: ignore[arg-type]
        )
        for c in chunks_dicts
    ]

    doc_titles = await _fetch_doc_titles_for_chunks(chunks_dicts)
    context = _build_context(scored_chunks, doc_titles)

    # Summary-intent enrichment: prepend cached executive summary (scope=single only)
    if scope == "single" and state.get("doc_ids") and _should_use_summary(question):
        try:
            from app.services.summarizer import (  # noqa: PLC0415
                get_summarization_service,
            )

            exec_summary = await get_summarization_service()._fetch_cached(
                state["doc_ids"][0], "executive"
            )
            if exec_summary:
                context = f"[Document Summary]\n{exec_summary.content}\n\n---\n\n{context}"
                logger.debug(
                    "synthesize_node: prepended executive summary",
                    extra={"document_id": state["doc_ids"][0]},
                )
        except Exception:
            logger.warning("synthesize_node: failed to fetch executive summary", exc_info=True)

    prompt = f"Context:\n\n{context}\n\nQuestion: {question}"

    llm = get_llm_service()
    try:
        token_gen = await llm.generate(prompt, system=QA_SYSTEM_PROMPT, model=model, stream=True)
        collected: list[str] = []
        async for token in token_gen:
            collected.append(token)
    except (litellm.ServiceUnavailableError, ValueError, litellm.AuthenticationError):
        raise  # propagate typed errors so stream_answer surfaces them correctly
    except Exception:
        raise  # propagate all LLM errors

    full_text = "".join(collected)

    if NOT_FOUND_SENTINEL in full_text:
        return {"not_found": True}

    answer_text, citations, confidence = _split_response(full_text)
    citations = _enrich_citation_titles(citations, scored_chunks, doc_titles, scope)

    return {
        "answer": answer_text,
        "citations": citations,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Graph construction + singleton
# ---------------------------------------------------------------------------


def build_chat_graph() -> StateGraph:
    """Build the V2 chat StateGraph."""
    g: StateGraph = StateGraph(ChatState)  # type: ignore[type-var]

    g.add_node("classify_node", classify_node)
    g.add_node("summary_node", summary_node)
    g.add_node("search_node", search_node)
    g.add_node("graph_node", graph_node)
    g.add_node("comparative_node", comparative_node)
    g.add_node("synthesize_node", synthesize_node)

    g.set_entry_point("classify_node")

    g.add_conditional_edges(
        "classify_node",
        route_node,
        {
            "summary_node": "summary_node",
            "graph_node": "graph_node",
            "comparative_node": "comparative_node",
            "search_node": "search_node",
        },
    )

    for node in ("summary_node", "search_node", "graph_node", "comparative_node"):
        g.add_edge(node, "synthesize_node")

    g.add_edge("synthesize_node", END)

    return g


_compiled_graph = None


def get_chat_graph():
    """Return the compiled chat graph singleton."""
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        _compiled_graph = build_chat_graph().compile()
    return _compiled_graph
