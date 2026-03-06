"""LangGraph StateGraph for the V2 agentic chat router.

S77: skeleton with stub strategy nodes.
S78: real implementations for all strategy nodes.

Graph flow:
    classify_node
      → [conditional by intent]
        → summary_node    → [conditional fallthrough] → synthesize_node → END
        → graph_node      → [conditional fallthrough] → synthesize_node → END
        → comparative_node → synthesize_node → END
        → search_node      → synthesize_node → END

Strategy nodes:
    summary_node     — intent='summary': fetch executive summary from DB
    graph_node       — intent='relational': Kuzu entity traversal + hybrid retrieval
    comparative_node — intent='comparative': dual retrieval with interleaving
    search_node      — intent='factual'|'exploratory': hybrid retrieval + section augmentation
"""

import asyncio
import logging
import re

import litellm
from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, LibrarySummaryModel, SectionSummaryModel, SummaryModel
from app.services.intent import _llm_classify_fallback, classify_intent_heuristic
from app.services.llm import get_llm_service
from app.services.qa import (
    NOT_FOUND_SENTINEL,
    QA_SYSTEM_PROMPT,
    _enrich_citation_titles,
    _maybe_rewrite_query,
    _should_use_summary,
    _split_response,
)
from app.services.retriever import get_retriever
from app.types import ChatState, ScoredChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent-specific system prompts (used by synthesize_node)
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = (
    "You are a knowledge assistant. Answer using the provided document summary. "
    "Be concise and well-structured. Use Markdown headings and bullet points. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}."
)

_RELATIONAL_SYSTEM = (
    "You are a knowledge assistant. Answer using the knowledge graph connections "
    "and the supporting passages provided. Name the entities clearly. "
    "Use Markdown to show relationships between entities. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    'Then on a new line write this JSON: {"citations":[],"confidence":"high|medium|low"}'
)

_COMPARATIVE_SYSTEM = (
    "You are a knowledge assistant. Compare the two subjects using the provided passages. "
    "Structure your answer as: **Subject A:** ... **Subject B:** ... "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    'Then on a new line write this JSON: {"citations":[],"confidence":"high|medium|low"}'
)


def _get_system_prompt(intent: str | None) -> str:
    """Return intent-appropriate system prompt for the LLM call."""
    if intent == "summary":
        return _SUMMARY_SYSTEM
    if intent == "relational":
        return _RELATIONAL_SYSTEM
    if intent == "comparative":
        return _COMPARATIVE_SYSTEM
    return QA_SYSTEM_PROMPT


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

    logger.debug("classify_node: intent=%s confidence=%.2f", intent, confidence)
    return {"intent": intent, "rewritten_question": rewritten}


# ---------------------------------------------------------------------------
# route_node — conditional edge function after classify_node
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
    return "search_node"


def _route_after_strategy(state: ChatState) -> str:
    """Conditional edge after summary_node / graph_node.

    If the node could not satisfy the query (sets intent='factual' as a fallthrough
    signal), re-route to search_node.  Otherwise proceed to synthesize_node.
    """
    if state.get("intent") == "factual":
        return "search_node"
    return "synthesize_node"


# ---------------------------------------------------------------------------
# summary_node — fetch executive summary from DB
# ---------------------------------------------------------------------------


async def _fetch_executive_summary(
    doc_ids: list[str], scope: str
) -> str | None:
    """Return executive summary content for the given scope, or None if absent."""
    async with get_session_factory()() as session:
        if scope == "single" and doc_ids:
            row = await session.execute(
                select(SummaryModel.content)
                .where(
                    SummaryModel.document_id == doc_ids[0],
                    SummaryModel.mode == "executive",
                )
                .order_by(SummaryModel.created_at.desc())
                .limit(1)
            )
        else:
            row = await session.execute(
                select(LibrarySummaryModel.content)
                .where(LibrarySummaryModel.mode == "executive")
                .order_by(LibrarySummaryModel.created_at.desc())
                .limit(1)
            )
        result = row.scalar_one_or_none()
    return result


async def summary_node(state: ChatState) -> dict:
    """Fetch executive summary from DB; fall through to search if absent."""
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")

    try:
        summary_content = await _fetch_executive_summary(doc_ids, scope)
    except Exception:
        logger.warning("summary_node: DB lookup failed", exc_info=True)
        summary_content = None

    if not summary_content:
        # No summary available — fall through to search_node
        logger.debug("summary_node: no executive summary found, falling through to search")
        return {"intent": "factual"}

    logger.debug("summary_node: executive summary found (%d chars)", len(summary_content))
    return {
        "section_context": summary_content,
        "chunks": [],
        "answer": "",
    }


# ---------------------------------------------------------------------------
# graph_node — Kuzu entity relationship traversal
# ---------------------------------------------------------------------------

_ENTITY_RE = re.compile(r'["\']([^"\']{2,})["\']')
_CAPITALIZED_RE = re.compile(r'\b([A-Z][a-zA-Z]{2,})\b')


def _extract_entities_from_question(question: str) -> list[str]:
    """Extract potential entity names from a question.

    Finds quoted strings first, then capitalized words (skipping first word).
    """
    entities: list[str] = []
    seen: set[str] = set()

    # Quoted strings
    for m in _ENTITY_RE.finditer(question):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            entities.append(name)

    # Capitalized words (skip first word of the question)
    words = question.split()
    for word in words[1:]:
        clean = re.sub(r"[^\w]", "", word)
        if clean and clean[0].isupper() and len(clean) > 2 and clean not in seen:
            seen.add(clean)
            entities.append(clean)

    return entities


def _query_kuzu_for_entity(conn, name: str) -> list[str]:
    """Return formatted relationship strings for one entity from Kuzu."""
    lines: list[str] = []
    # CO_OCCURS edges
    try:
        r = conn.execute(
            "MATCH (e:Entity {name: $n})-[r:CO_OCCURS]->(b:Entity)"
            " RETURN b.name, r.weight ORDER BY r.weight DESC LIMIT 10",
            {"n": name},
        )
        while r.has_next():
            row = r.get_next()
            related_name, weight = row[0], row[1]
            if related_name:
                lines.append(f"{name} --co-occurs--> {related_name} (weight={weight:.1f})")
    except Exception:
        pass
    # RELATED_TO edges
    try:
        r = conn.execute(
            "MATCH (e:Entity {name: $n})-[r:RELATED_TO]->(b:Entity)"
            " RETURN b.name, r.relation_label LIMIT 10",
            {"n": name},
        )
        while r.has_next():
            row = r.get_next()
            related_name, relation = row[0], row[1]
            if related_name:
                lines.append(f"{name} --{relation or 'related'}--> {related_name}")
    except Exception:
        pass
    return lines


async def graph_node(state: ChatState) -> dict:
    """Kuzu entity traversal for relational queries.

    Extracts entity names from the question, queries CO_OCCURS + RELATED_TO edges,
    and runs hybrid retrieval (k=5) as a grounding supplement.
    Falls through to search_node (via intent='factual') on Kuzu failure or 0 results.
    """
    question = state["question"]
    q = state.get("rewritten_question") or question
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None

    entity_names = _extract_entities_from_question(question)
    graph_lines: list[str] = []

    try:
        from app.services.graph import get_graph_service  # noqa: PLC0415

        conn = get_graph_service()._conn
        for name in entity_names[:5]:  # cap at 5 entities
            graph_lines.extend(_query_kuzu_for_entity(conn, name))
    except Exception:
        logger.warning("graph_node: Kuzu query failed", exc_info=True)

    if not graph_lines:
        logger.debug("graph_node: no graph results, falling through to search")
        return {"intent": "factual"}

    section_context = "Knowledge graph connections:\n" + "\n".join(graph_lines)

    # Grounding supplement: hybrid retrieval k=5
    chunks_dicts: list[dict] = []
    try:
        retriever = get_retriever()
        chunks: list[ScoredChunk] = await retriever.retrieve(q, effective_doc_ids, k=5)
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
        logger.warning("graph_node: retrieval failed", exc_info=True)

    return {
        "section_context": section_context,
        "chunks": chunks_dicts,
    }


# ---------------------------------------------------------------------------
# comparative_node — dual retrieval with side detection + interleaving
# ---------------------------------------------------------------------------

_BETWEEN_RE = re.compile(
    r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:\?|$)", re.IGNORECASE
)
_VS_RE = re.compile(
    r"(.+?)\s+(?:versus|vs\.?)\s+(.+?)(?:\?|$)", re.IGNORECASE
)


def _detect_comparison_sides(question: str) -> tuple[str, str] | None:
    """Return (side_a, side_b) if comparison sides can be detected, else None."""
    m = _BETWEEN_RE.search(question)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _VS_RE.search(question)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None


def _interleave(a: list, b: list) -> list:
    """Interleave two lists: [a0, b0, a1, b1, ...]."""
    result: list = []
    for x, y in zip(a, b):
        result.append(x)
        result.append(y)
    # Append remainder from the longer list
    result.extend(a[len(b) :])
    result.extend(b[len(a) :])
    return result


def _chunk_to_dict(c: ScoredChunk) -> dict:
    return {
        "chunk_id": c.chunk_id,
        "document_id": c.document_id,
        "text": c.text,
        "section_heading": c.section_heading,
        "page": c.page,
        "score": c.score,
        "source": c.source,
    }


async def comparative_node(state: ChatState) -> dict:
    """Dual retrieval with side detection; interleaves results for structured comparison."""
    question = state["question"]
    q = state.get("rewritten_question") or question
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None

    sides = _detect_comparison_sides(question)
    retriever = get_retriever()

    try:
        if sides:
            side_a, side_b = sides
            chunks_a, chunks_b = await asyncio.gather(
                retriever.retrieve(side_a, effective_doc_ids, k=5),
                retriever.retrieve(side_b, effective_doc_ids, k=5),
            )
            interleaved = _interleave(
                [_chunk_to_dict(c) for c in chunks_a],
                [_chunk_to_dict(c) for c in chunks_b],
            )
        else:
            chunks = await retriever.retrieve(q, effective_doc_ids, k=10)
            interleaved = [_chunk_to_dict(c) for c in chunks]
    except Exception:
        logger.warning("comparative_node: retrieval failed", exc_info=True)
        interleaved = []

    return {
        "chunks": interleaved,
        "section_context": f"Comparison query: {question}",
    }


# ---------------------------------------------------------------------------
# search_node — hybrid retrieval with section summary augmentation
# ---------------------------------------------------------------------------


async def _fetch_section_summaries(
    doc_heading_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Batch-fetch SectionSummaryModel rows by (document_id, heading).

    Returns a dict mapping (document_id, heading) -> summary content.
    """
    if not doc_heading_pairs:
        return {}
    async with get_session_factory()() as session:
        # Build OR conditions for all (doc_id, heading) pairs
        from sqlalchemy import and_, or_  # noqa: PLC0415

        conditions = [
            and_(
                SectionSummaryModel.document_id == doc_id,
                SectionSummaryModel.heading == heading,
            )
            for doc_id, heading in doc_heading_pairs
        ]
        rows = await session.execute(
            select(
                SectionSummaryModel.document_id,
                SectionSummaryModel.heading,
                SectionSummaryModel.content,
            ).where(or_(*conditions))
        )
        return {(row.document_id, row.heading): row.content for row in rows}


async def search_node(state: ChatState) -> dict:
    """Hybrid retrieval with section summary augmentation.

    For each retrieved chunk that has a section_heading, looks up its
    SectionSummaryModel row and prepends the summary:
        ### {heading}
        {section_summary}
        ---
        {chunk_text}
    """
    q = state.get("rewritten_question") or state["question"]
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None

    chunks_dicts: list[dict] = []
    try:
        retriever = get_retriever()
        chunks: list[ScoredChunk] = await retriever.retrieve(q, effective_doc_ids, k=10)

        # Batch-fetch section summaries for all (document_id, section_heading) pairs
        pairs = [
            (c.document_id, c.section_heading)
            for c in chunks
            if c.section_heading
        ]
        section_summary_map = await _fetch_section_summaries(pairs)

        for c in chunks:
            section_summary = (
                section_summary_map.get((c.document_id, c.section_heading))
                if c.section_heading
                else None
            )
            augmented_text = c.text
            if section_summary:
                augmented_text = (
                    f"### {c.section_heading}\n"
                    f"{section_summary}\n"
                    f"---\n"
                    f"{c.text}"
                )

            chunks_dicts.append(
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "text": augmented_text,
                    "section_heading": c.section_heading,
                    "section_summary": section_summary,
                    "page": c.page,
                    "score": c.score,
                    "source": c.source,
                }
            )
    except Exception:
        logger.warning("search_node: retrieval failed", exc_info=True)

    return {"chunks": chunks_dicts}


# ---------------------------------------------------------------------------
# synthesize_node — intent-aware LLM call
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
    """Call LLM with intent-appropriate prompt; parse answer/citations/confidence.

    Pass-through: if a strategy node already set a non-empty answer, returns {}.
    No-context: if both chunks and section_context are absent, returns {"not_found": True}.
    LLM errors are re-raised so stream_answer() can surface them with correct SSE events.
    """
    existing_answer = state.get("answer", "")
    if existing_answer:
        return {}

    chunks_dicts = state.get("chunks") or []
    section_context = state.get("section_context")
    question = state["question"]
    model = state.get("model")
    scope = state.get("scope", "all")
    intent = state.get("intent")

    if not chunks_dicts and not section_context:
        return {"not_found": True}

    from app.services.context_packer import pack_context  # noqa: PLC0415

    # Reconstruct ScoredChunk objects for _enrich_citation_titles
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

    # Assemble chunk context using the pure context packer (dedup + section grouping)
    chunks_context = pack_context(chunks_dicts, token_budget=3000) if chunks_dicts else ""

    # section_context (graph results, executive summary) capped at 1000 tokens
    context_parts: list[str] = []
    if section_context:
        words = section_context.split()
        cap_words = int(1000 / 1.3)  # approx word count for 1000 tokens
        if len(words) > cap_words:
            section_context = " ".join(words[:cap_words]) + " ..."
        context_parts.append(section_context)

    if chunks_context:
        context_parts.append(chunks_context)

    context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    # For summary intent with scope=single: also prepend executive summary if chunks present
    if (
        intent != "summary"
        and scope == "single"
        and state.get("doc_ids")
        and _should_use_summary(question)
    ):
        try:
            from app.services.summarizer import (  # noqa: PLC0415
                get_summarization_service,
            )

            exec_summary = await get_summarization_service()._fetch_cached(
                state["doc_ids"][0], "executive"
            )
            if exec_summary:
                context = f"[Document Summary]\n{exec_summary.content}\n\n---\n\n{context}"
        except Exception:
            logger.warning("synthesize_node: failed to fetch executive summary", exc_info=True)

    prompt = f"Context:\n\n{context}\n\nQuestion: {question}"
    system_prompt = _get_system_prompt(intent)

    llm = get_llm_service()
    try:
        token_gen = await llm.generate(prompt, system=system_prompt, model=model, stream=True)
        collected: list[str] = []
        async for token in token_gen:
            collected.append(token)
    except (litellm.ServiceUnavailableError, ValueError, litellm.AuthenticationError):
        raise
    except Exception:
        raise

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

    g.add_edge("comparative_node", "synthesize_node")
    g.add_edge("search_node", "synthesize_node")
    g.add_edge("synthesize_node", END)

    return g


_compiled_graph = None


def get_chat_graph():
    """Return the compiled chat graph singleton."""
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        _compiled_graph = build_chat_graph().compile()
    return _compiled_graph
