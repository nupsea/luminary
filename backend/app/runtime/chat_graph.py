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

import asyncio
import json
import logging
import re

import litellm
from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, SectionSummaryModel, SummaryModel
from app.services.intent import _llm_classify_fallback, classify_intent_heuristic
from app.services.qa import (
    NOT_FOUND_SENTINEL,
    QA_SYSTEM_PROMPT,
    _maybe_rewrite_query,
    _should_use_summary,
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
    scope = state.get("scope", "all")
    doc_ids = state.get("doc_ids") or []

    logger.info(
        "chat: question=%r scope=%s docs=%d",
        question[:80], scope, len(doc_ids),
    )

    intent, confidence = classify_intent_heuristic(question)
    source = "heuristic"

    if confidence < 0.7:
        intent = await _llm_classify_fallback(question, scope=scope, default=intent)
        source = "llm"

    logger.info(
        "classify_node: intent=%s confidence=%.2f source=%s",
        intent, confidence, source,
    )

    # Query rewriting via Kuzu entities — non-fatal
    effective_doc_ids = doc_ids if state.get("scope") == "single" else None
    try:
        rewritten = await _maybe_rewrite_query(question, effective_doc_ids)
        if rewritten != question:
            logger.info("classify_node: query rewritten → %r", rewritten[:80])
    except Exception:
        rewritten = question

    _intent_to_strategy = {
        "summary": "summary_node",
        "relational": "graph_node",
        "comparative": "comparative_node",
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
    if intent == "summary":
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


# ---------------------------------------------------------------------------
# summary_node — fetch executive summary from DB
# ---------------------------------------------------------------------------


async def _fetch_single_doc_executive_summary(doc_id: str) -> str | None:
    """Return executive summary content for a single document, or None if absent."""
    async with get_session_factory()() as session:
        row = await session.execute(
            select(SummaryModel.content)
            .where(
                SummaryModel.document_id == doc_id,
                SummaryModel.mode == "executive",
            )
            .order_by(SummaryModel.created_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


async def _fetch_all_doc_executive_summaries() -> list[tuple[str, str]]:
    """Return (document_title, summary_content) for every doc that has an executive summary.

    Fetches the latest executive summary per document via a single joined query.
    Returns an empty list if none exist.
    """
    async with get_session_factory()() as session:
        from sqlalchemy import func  # noqa: PLC0415

        # Latest created_at per document_id
        latest_subq = (
            select(
                SummaryModel.document_id,
                func.max(SummaryModel.created_at).label("max_ts"),
            )
            .where(SummaryModel.mode == "executive")
            .group_by(SummaryModel.document_id)
            .subquery()
        )
        rows = await session.execute(
            select(DocumentModel.title, SummaryModel.content)
            .join(DocumentModel, DocumentModel.id == SummaryModel.document_id)
            .join(
                latest_subq,
                (SummaryModel.document_id == latest_subq.c.document_id)
                & (SummaryModel.created_at == latest_subq.c.max_ts),
            )
            .order_by(DocumentModel.title)
        )
        return [(row.title, row.content) for row in rows]


async def summary_node(state: ChatState) -> dict:
    """Fetch executive summary from DB; fall through to search if absent.

    scope='single': fetch this document's executive summary and set answer directly
                    (no LLM call — the cached summary IS the answer).
    scope='all':    fetch per-document executive summaries for ALL docs in parallel,
                    format them as section_context so synthesize_node calls the LLM
                    to synthesize a cross-library answer with proper citations.
    """
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")

    logger.info("summary_node: scope=%s", scope)

    if scope == "single" and doc_ids:
        try:
            summary_content = await _fetch_single_doc_executive_summary(doc_ids[0])
        except Exception:
            logger.warning("summary_node: single-doc DB lookup failed", exc_info=True)
            summary_content = None

        if not summary_content:
            logger.info(
                "summary_node: no cached summary for doc %s — falling through to search",
                doc_ids[0],
            )
            return {"intent": "factual"}

        logger.info(
            "summary_node: serving cached summary (%d chars), skipping LLM call",
            len(summary_content),
        )
        return {
            "answer": summary_content,
            "confidence": "high",
            "chunks": [],
        }

    # scope='all': fetch every document's executive summary and synthesize via LLM
    try:
        doc_summaries = await _fetch_all_doc_executive_summaries()
    except Exception:
        logger.warning("summary_node: all-docs DB lookup failed", exc_info=True)
        doc_summaries = []

    if not doc_summaries:
        logger.info(
            "summary_node: no executive summaries exist for any document"
            " — falling through to search"
        )
        return {"intent": "factual"}

    logger.info(
        "summary_node: found %d document summaries — sending to LLM for synthesis",
        len(doc_summaries),
    )
    parts = [f"[Document: {title}]\n{content}" for title, content in doc_summaries]
    section_context = "\n\n---\n\n".join(parts)
    return {
        "section_context": section_context,
        "chunks": [],
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

    logger.info(
        "graph_node: extracted %d entities, got %d graph lines",
        len(entity_names), len(graph_lines),
    )

    if not graph_lines:
        logger.info("graph_node: no graph results — falling through to search")
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
# comparative_node — N-way comparison with LLM decomposition + document routing
# ---------------------------------------------------------------------------


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


def _round_robin(lists: list[list]) -> list:
    """Round-robin interleave N lists: [l0[0], l1[0], l2[0], l0[1], l1[1], ...]."""
    result: list = []
    iters = [iter(lst) for lst in lists]
    while True:
        advanced = False
        for it in iters:
            try:
                result.append(next(it))
                advanced = True
            except StopIteration:
                pass
        if not advanced:
            break
    return result


async def _decompose_comparison(question: str) -> dict | None:
    """LLM-decompose a comparison question into N sides and a topic.

    Returns {"sides": [list of subject names], "topic": str} or None on failure.
    Handles 2-way, 3-way, and any N-way comparisons.
    """
    from app.config import get_settings  # noqa: PLC0415

    try:
        model = get_settings().LITELLM_DEFAULT_MODEL
        response = await litellm.acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract ALL subjects being compared and the comparison topic. "
                        'Reply with exactly this JSON (no prose, no markdown): '
                        '{"sides": ["subject1", "subject2", ...], '
                        '"topic": "what is being compared"}. '
                        "sides must have 2 or more entries. "
                        "If you cannot extract this structure, reply: null"
                    ),
                },
                {"role": "user", "content": question},
            ],
            temperature=0.0,
        )
        text = (response.choices[0].message.content or "").strip()
        if text.lower() == "null":
            return None
        parsed = json.loads(text)
        sides = parsed.get("sides")
        topic = parsed.get("topic")
        if (
            isinstance(sides, list)
            and len(sides) >= 2
            and all(isinstance(s, str) and s.strip() for s in sides)
            and isinstance(topic, str)
            and topic.strip()
        ):
            return {"sides": [s.strip() for s in sides], "topic": topic.strip()}
    except Exception:
        logger.warning("_decompose_comparison: LLM call failed", exc_info=True)
    return None


async def _resolve_side_to_docs(
    side_name: str, scope_doc_ids: list[str] | None
) -> list[str]:
    """Resolve a comparison side (author, character, work title) to document IDs.

    Resolution order (results are unioned):
      1. Kuzu exact entity match  — Entity.name == side_name (case-insensitive)
      2. Kuzu partial entity match — Entity.name contains side_name
      3. SQLite document title match — title contains side_name

    An entity that appears in multiple documents (e.g. an author across several
    works) returns all of those document IDs.

    If scope_doc_ids is set, results are intersected with the allowed set.
    Returns [] if nothing matched — caller falls back to unfiltered retrieval.
    """
    doc_ids: set[str] = set()

    # Kuzu entity → document lookup
    try:
        from app.services.graph import get_graph_service  # noqa: PLC0415

        conn = get_graph_service()._conn
        r = conn.execute(
            "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document)"
            " WHERE lower(e.name) = lower($name)"
            " RETURN DISTINCT d.id",
            {"name": side_name},
        )
        while r.has_next():
            row = r.get_next()
            if row[0]:
                doc_ids.add(row[0])
        if not doc_ids:
            r = conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document)"
                " WHERE contains(lower(e.name), lower($name))"
                " RETURN DISTINCT d.id LIMIT 20",
                {"name": side_name},
            )
            while r.has_next():
                row = r.get_next()
                if row[0]:
                    doc_ids.add(row[0])
    except Exception:
        logger.warning(
            "_resolve_side_to_docs: Kuzu lookup failed for %r", side_name, exc_info=True
        )

    # Document title search — catches cases where the side name appears in a title
    try:
        from sqlalchemy import func  # noqa: PLC0415

        async with get_session_factory()() as session:
            rows = await session.execute(
                select(DocumentModel.id).where(
                    func.lower(DocumentModel.title).contains(side_name.lower())
                )
            )
            for row in rows:
                doc_ids.add(row.id)
    except Exception:
        logger.warning(
            "_resolve_side_to_docs: title search failed for %r", side_name, exc_info=True
        )

    resolved = list(doc_ids)
    if scope_doc_ids:
        resolved = [d for d in resolved if d in scope_doc_ids]
    return resolved


async def comparative_node(state: ChatState) -> dict:
    """N-way comparative retrieval with LLM decomposition and per-side document routing.

    Pipeline:
      1. LLM extracts N subjects and a comparison topic from the question.
      2. Each subject is resolved to its documents via entity graph + title search.
         A subject with multiple documents (e.g. an author with several works)
         gets all of its documents searched together.
      3. For each subject, retrieve topic-focused chunks filtered to that subject's
         documents. All retrievals run in parallel.
      4. Results are round-robin interleaved across all N subjects so no single
         subject dominates the context window.

    Falls back to unfiltered k=10 retrieval if LLM decomposition fails.
    """
    question = state["question"]
    q = state.get("rewritten_question") or question
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None
    retriever = get_retriever()

    decomposed = await _decompose_comparison(question)

    if decomposed:
        sides: list[str] = decomposed["sides"]
        topic: str = decomposed["topic"]

        logger.info(
            "comparative_node: %d sides=%s topic=%r",
            len(sides), sides, topic,
        )

        resolved: list[list[str]] = await asyncio.gather(
            *[_resolve_side_to_docs(side, effective_doc_ids) for side in sides]
        )

        k_per_side = max(4, 12 // len(sides))

        async def _retrieve_for_side(side: str, side_docs: list[str]) -> list[dict]:
            # If no docs resolved for this side, widen the query to include the
            # subject name so unfiltered retrieval still finds relevant passages.
            query = topic if side_docs else f"{side} {topic}"
            filter_ids = side_docs or effective_doc_ids
            try:
                chunks = await retriever.retrieve(query, filter_ids, k=k_per_side)
                return [_chunk_to_dict(c) for c in chunks]
            except Exception:
                logger.warning(
                    "comparative_node: retrieval failed for side %r", side, exc_info=True
                )
                return []

        per_side_chunks: list[list[dict]] = await asyncio.gather(
            *[_retrieve_for_side(side, docs) for side, docs in zip(sides, resolved)]
        )

        interleaved = _round_robin(per_side_chunks)

        side_labels = "; ".join(
            f"{side} ({len(docs)} doc(s))" for side, docs in zip(sides, resolved)
        )
        section_context = f"Comparing: {side_labels} — topic: {topic}"

        for side, docs in zip(sides, resolved):
            logger.info(
                "comparative_node: side=%r resolved to %d doc(s)", side, len(docs)
            )
        logger.info(
            "comparative_node: retrieving %d chunks per side, total=%d",
            k_per_side, len(interleaved),
        )
        return {"chunks": interleaved, "section_context": section_context}

    # Fallback: unfiltered retrieval when LLM decomposition fails
    logger.info("comparative_node: LLM decomposition failed — using unfiltered retrieval")
    try:
        chunks = await retriever.retrieve(q, effective_doc_ids, k=10)
        interleaved = [_chunk_to_dict(c) for c in chunks]
    except Exception:
        logger.warning("comparative_node: fallback retrieval failed", exc_info=True)
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

    logger.info(
        "search_node: query=%r scope=%s filter_docs=%s",
        q[:80], scope, len(effective_doc_ids) if effective_doc_ids else "all",
    )

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

    logger.info("search_node: returning %d chunks", len(chunks_dicts))
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
    """Prepare LLM prompt for stream_answer() to call streaming.

    Pass-through: if a strategy node already set a non-empty answer (e.g. summary_node
    with a cached executive summary), returns {} so stream_answer() uses that answer.
    No-context: if both chunks and section_context are absent, returns {"not_found": True}.

    True streaming design: synthesize_node prepares the prompt and system_prompt, stores
    them in state as _llm_prompt and _system_prompt, and returns WITHOUT calling the LLM.
    stream_answer() calls the LLM streaming and yields tokens progressively to the SSE
    client as they are generated, rather than buffering the full response first.
    """
    existing_answer = state.get("answer", "")
    if existing_answer:
        logger.info("synthesize_node: answer already set — pass-through, skipping LLM call")
        return {}

    chunks_dicts = state.get("chunks") or []
    section_context = state.get("section_context")
    question = state["question"]
    scope = state.get("scope", "all")
    intent = state.get("intent")

    if not chunks_dicts and not section_context:
        logger.info("synthesize_node: no context available — returning not_found")
        return {"not_found": True}

    logger.info(
        "synthesize_node: intent=%s chunks=%d section_context=%s",
        intent, len(chunks_dicts), "yes" if section_context else "no",
    )

    from app.services.context_packer import pack_context  # noqa: PLC0415

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

    # Return prompt fields for stream_answer() to call the LLM streaming directly.
    # This enables true token-by-token streaming: the first SSE token event is sent
    # as the LLM generates it, not after all tokens are buffered.
    return {"_llm_prompt": prompt, "_system_prompt": system_prompt}


# ---------------------------------------------------------------------------
# confidence_gate_node + augment_node (S81)
# ---------------------------------------------------------------------------


async def confidence_gate_node(state: ChatState) -> dict:
    """No-op node; routing decision is made by _route_after_confidence_gate."""
    confidence = state.get("confidence", "low")
    retry_attempted = state.get("retry_attempted", False)
    logger.info(
        "confidence_gate_node: confidence=%s retry_attempted=%s",
        confidence, retry_attempted,
    )
    return {}


def _route_after_confidence_gate(state: ChatState) -> str:
    """Conditional edge after confidence_gate_node.

    Routes to END unless confidence is 'low' AND this is the first attempt.
    Guarantees at most 1 retry loop.
    """
    confidence = state.get("confidence", "low")
    retry_attempted = state.get("retry_attempted", False)
    if confidence == "low" and not retry_attempted:
        logger.info("confidence_gate_node: low confidence, triggering augment retry")
        return "augment_node"
    logger.info("confidence_gate_node: confidence=%s — routing to END", confidence)
    return END


async def augment_node(state: ChatState) -> dict:
    """Augment context with a complementary strategy when confidence is low.

    Selects the complementary strategy based on primary_strategy:
      search_node / factual / exploratory → Kuzu entity graph lines → section_context
      graph_node (relational)             → hybrid search k=15 → chunks
      summary_node                        → hybrid search k=10 → chunks
      comparative_node                    → hybrid search k=10, no doc filter → chunks

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

    except Exception:
        logger.warning("augment_node: augmentation failed", exc_info=True)
        return {"retry_attempted": True}

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
        len(new_chunks), len(new_section_lines), len(combined_chunks),
    )
    return {
        "chunks": combined_chunks,
        "section_context": combined_section_context,
        "retry_attempted": True,
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
    g.add_node("summary_node", summary_node)
    g.add_node("search_node", search_node)
    g.add_node("graph_node", graph_node)
    g.add_node("comparative_node", comparative_node)
    g.add_node("synthesize_node", synthesize_node)
    g.add_node("confidence_gate_node", confidence_gate_node)
    g.add_node("augment_node", augment_node)

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

    # synthesize_node → confidence_gate_node → (END | augment_node)
    g.add_edge("synthesize_node", "confidence_gate_node")
    g.add_conditional_edges(
        "confidence_gate_node",
        _route_after_confidence_gate,
        {
            "augment_node": "augment_node",
            END: END,
        },
    )
    # Retry path: augment_node → synthesize_node → confidence_gate_node → END
    g.add_edge("augment_node", "synthesize_node")

    return g


_compiled_graph = None


def get_chat_graph():
    """Return the compiled chat graph singleton."""
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        _compiled_graph = build_chat_graph().compile()
    return _compiled_graph
