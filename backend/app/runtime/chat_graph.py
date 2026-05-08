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
import logging

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.database import get_session_factory
from app.models import (
    ChunkModel,
    DocumentModel,
    SectionSummaryModel,
)
from app.runtime.chat_nodes._shared import (
    _chunk_to_dict,
    _get_system_prompt,
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
from app.services.intent import _llm_classify_fallback, classify_intent_heuristic
from app.services.qa import (
    _maybe_rewrite_query,
    _should_use_summary,
)
from app.services.retriever import get_retriever
from app.types import ChatState, ScoredChunk, TransparencyInfo

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


async def _fetch_neighbor_chunks(
    chunk_id: str, document_id: str, chunk_index: int
) -> list[tuple[int, str]]:
    """Fetch immediate neighbors (index-1, index+1) for a chunk to expand context."""
    async with get_session_factory()() as session:
        from app.models import ChunkModel  # noqa: PLC0415

        stmt = select(ChunkModel.chunk_index, ChunkModel.text).where(
            ChunkModel.document_id == document_id,
            ChunkModel.chunk_index.in_([chunk_index - 1, chunk_index + 1]),
        )
        rows = await session.execute(stmt)
        return [(row.chunk_index, row.text) for row in rows]


async def search_node(state: ChatState) -> dict:
    """Hybrid retrieval with context expansion and section summary augmentation.

    Context Expansion (Parent-Child):
    For each retrieved chunk, we fetch its immediate neighbors (index-1 and index+1)
    to provide a more coherent window to the LLM. This prevents "chopped up"
    information from hurting the answer quality.
    """
    q = state.get("rewritten_question") or state["question"]
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None

    logger.info(
        "search_node: query=%r scope=%s filter_docs=%s",
        q[:80],
        scope,
        len(effective_doc_ids) if effective_doc_ids else "all",
    )

    # For library-wide queries use a tighter k to avoid scattered context
    k = 6 if scope == "all" else 10

    chunks_dicts: list[dict] = []
    image_ids: list[str] = []
    try:
        retriever = get_retriever()
        chunks: list[ScoredChunk]
        chunks, image_ids = await retriever.retrieve_with_images(q, effective_doc_ids, k=k)

        # Batch-fetch section summaries for all (document_id, section_heading) pairs
        pairs = [(c.document_id, c.section_heading) for c in chunks if c.section_heading]
        section_summary_map = await _fetch_section_summaries(pairs)

        # Context Expansion: fetch neighbors for each chunk
        neighbor_tasks = [
            _fetch_neighbor_chunks(c.chunk_id, c.document_id, c.chunk_index)
            if hasattr(c, "chunk_index")
            else asyncio.sleep(0, result=[])
            for c in chunks
        ]
        neighbors_list = await asyncio.gather(*neighbor_tasks)

        for c, neighbors in zip(chunks, neighbors_list, strict=False):
            # Sort and combine neighbors with the current chunk
            all_parts = [(c.chunk_index, c.text)] + (
                neighbors if isinstance(neighbors, list) else []
            )
            all_parts.sort(key=lambda x: x[0])
            expanded_text = "\n\n".join([p[1] for p in all_parts])

            section_summary = (
                section_summary_map.get((c.document_id, c.section_heading))
                if c.section_heading
                else None
            )
            augmented_text = expanded_text
            if section_summary:
                augmented_text = f"### {c.section_heading}\n{section_summary}\n---\n{expanded_text}"

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

    # For scope='all': cap at 2 chunks per document so no single doc dominates context
    if scope == "all" and chunks_dicts:
        from app.services.context_packer import _cap_per_document  # noqa: PLC0415

        chunks_dicts = _cap_per_document(chunks_dicts, max_per_doc=2)

    logger.info("search_node: returning %d chunks, %d image_ids", len(chunks_dicts), len(image_ids))
    return {"chunks": chunks_dicts, "image_ids": image_ids}


# notes_node + notes_gap_node live in chat_nodes/notes.py and are
# re-exported above for back-compat.


# socratic_node + teach_back_node live in chat_nodes/socratic.py and are
# re-exported above for back-compat.


# ---------------------------------------------------------------------------
# synthesize_node — intent-aware LLM call
# ---------------------------------------------------------------------------


async def _fetch_doc_titles_for_chunks(chunks_dicts: list[dict]) -> dict[str, str]:
    doc_ids = list({c["document_id"] for c in chunks_dicts if c.get("document_id")})
    if not doc_ids:
        return {}
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(DocumentModel.id, DocumentModel.title).where(DocumentModel.id.in_(doc_ids))
        )
        return {row.id: row.title for row in rows}


async def _fetch_section_ids_and_pages_for_chunks(
    chunk_ids: list[str],
) -> dict[str, tuple[str | None, int | None]]:
    """Return {chunk_id: (section_id, pdf_page_number)} for the given chunk_ids.

    Used by synthesize_node to build SourceCitation entries from retrieved chunks.
    Returns {} on any DB error (non-fatal).
    """
    if not chunk_ids:
        return {}
    try:
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(ChunkModel.id, ChunkModel.section_id, ChunkModel.pdf_page_number).where(
                    ChunkModel.id.in_(chunk_ids)
                )
            )
            return {row.id: (row.section_id, row.pdf_page_number) for row in rows}
    except Exception:
        logger.warning("_fetch_section_ids_and_pages_for_chunks: DB lookup failed", exc_info=True)
        return {}


async def _fetch_contradiction_context(doc_ids: list[str]) -> str:
    """Return a formatted context block of SAME_CONCEPT contradictions for the given documents.

    Fetches SAME_CONCEPT edges with contradiction=True that involve any of the given doc_ids.
    Looks up publication_year to include '[YYYY source preferred]' when available.
    Returns empty string if no contradictions exist or on any error.
    Caps output at 3 contradictions to avoid prompt bloat.
    """
    from app.services.graph import get_graph_service  # noqa: PLC0415

    try:
        svc = get_graph_service()
        all_edges = svc.get_same_concept_edges()
        relevant = [
            e
            for e in all_edges
            if e["contradiction"]
            and (e["source_doc_id"] in doc_ids or e["target_doc_id"] in doc_ids)
        ]
        if not relevant:
            return ""

        # Look up publication years for the documents involved
        all_doc_ids: set[str] = set()
        for e in relevant:
            all_doc_ids.add(e["source_doc_id"])
            all_doc_ids.add(e["target_doc_id"])

        doc_years: dict[str, int | None] = {}
        try:
            async with get_session_factory()() as session:
                rows = await session.execute(
                    select(DocumentModel.id, DocumentModel.publication_year).where(
                        DocumentModel.id.in_(list(all_doc_ids))
                    )
                )
                for row in rows:
                    doc_years[row.id] = row.publication_year
        except Exception:
            logger.debug("_fetch_contradiction_context: year lookup failed", exc_info=True)

        lines: list[str] = ["[Cross-source contradictions detected:]"]
        for e in relevant[:3]:
            prefer = ""
            if e["prefer_source"] == "b":
                year = doc_years.get(e["target_doc_id"])
                prefer = f" [{year} source preferred]" if year else " (newer source preferred)"
            elif e["prefer_source"] == "a":
                year = doc_years.get(e["source_doc_id"])
                prefer = f" [{year} source preferred]" if year else " (first source preferred)"
            lines.append(f'- Concept "{e["name_a"]}": {e["contradiction_note"]}{prefer}')
        return "\n".join(lines)
    except Exception:
        logger.debug("_fetch_contradiction_context failed", exc_info=True)
        return ""


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
        intent,
        len(chunks_dicts),
        "yes" if section_context else "no",
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

    # Inject conversation history before retrieval context.
    # Cap at ~385 words (~500 tokens) to protect the retrieval context budget.
    # Most-recent messages are kept when trimming is needed.
    conversation_history = state.get("conversation_history") or []
    history_block = ""
    if conversation_history:
        all_lines: list[str] = []
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            label = "User" if role == "user" else "Assistant"
            all_lines.append(f"{label}: {content}")
        # Keep as many lines as fit within the word cap, prioritising recent turns.
        lines_to_include: list[str] = []
        word_count = 0
        for line in reversed(all_lines):
            words = len(line.split())
            if word_count + words > 385:
                break
            lines_to_include.insert(0, line)
            word_count += words
        if lines_to_include:
            history_block = "Prior conversation (most recent last):\n" + "\n".join(lines_to_include)

    if history_block:
        prompt = f"{history_block}\n\nContext:\n\n{context}\n\nQuestion: {question}"
    else:
        prompt = f"Context:\n\n{context}\n\nQuestion: {question}"
    system_prompt = _get_system_prompt(intent)

    # For library-wide factual/exploratory queries, instruct the LLM to attribute sources
    if scope == "all" and intent in ("factual", "exploratory"):
        system_prompt = (
            system_prompt + "\n\nThe user is asking about their entire library. "
            "Answer using only the provided passages. "
            "If the passages come from multiple documents, synthesise across them. "
            "Be explicit about which document each point comes from."
        )

    # Inject SAME_CONCEPT contradiction context for scope=all (S141)
    if scope == "all" and state.get("doc_ids"):
        try:
            contradiction_ctx = await _fetch_contradiction_context(state["doc_ids"])
            if contradiction_ctx:
                context = contradiction_ctx + "\n\n---\n\n" + context
                logger.info(
                    "synthesize_node: injected contradiction context (%d chars)",
                    len(contradiction_ctx),
                )
        except Exception:
            logger.debug("synthesize_node: contradiction context fetch failed", exc_info=True)

    # Inject version-mismatch detection instruction when web snippets are present (S142)
    web_snippets = state.get("web_snippets") or []
    if web_snippets:
        web_versions = [s.get("version_info", "") for s in web_snippets if s.get("version_info")]
        if web_versions:
            system_prompt = (
                system_prompt + "\n\nSome context comes from web sources labeled [Web: ...]. "
                "If the web source mentions a newer version than the local content "
                "(e.g. 'Python 3.12' vs 'Python 3.9'), explicitly note the discrepancy: "
                "'Your book covers X [Local]. The current recommendation is Y [Web: domain].' "
                "In the citations JSON, add version_mismatch=true to any citation where "
                "a version discrepancy is detected between local and web content."
            )

    # S148: collect SourceCitations from context chunks for post-stream emission.
    # Deduplicate by section_id (first occurrence wins); when section_id is None,
    # fall back to chunk_id so each unlinked chunk gets its own citation entry.
    chunk_meta: dict = {}  # chunk_id -> (section_id, pdf_page); populated below if chunks present
    source_citations_out: list[dict] = []
    if chunks_dicts:
        chunk_ids = [c["chunk_id"] for c in chunks_dicts if c.get("chunk_id")]
        chunk_meta = await _fetch_section_ids_and_pages_for_chunks(chunk_ids)
        doc_titles_map = await _fetch_doc_titles_for_chunks(chunks_dicts)

        seen_dedup_keys: set[str] = set()
        for c in chunks_dicts:
            cid = c.get("chunk_id", "")
            meta = chunk_meta.get(cid, (None, None))
            section_id, pdf_page = meta
            doc_id = c.get("document_id", "")
            doc_title = doc_titles_map.get(doc_id, "")
            section_heading = c.get("section_heading", "")

            # Dedup key: (section_id, page) for PDFs so different pages in the same
            # section produce separate citations; section_id alone for non-PDFs.
            if pdf_page is not None and section_id:
                dedup_key = f"{section_id}:{pdf_page}"
            elif section_id:
                dedup_key = section_id
            else:
                dedup_key = cid
            if dedup_key in seen_dedup_keys:
                continue
            seen_dedup_keys.add(dedup_key)

            chunk_text = c.get("text", "") or ""
            source_citations_out.append(
                {
                    "chunk_id": cid,
                    "document_id": doc_id,
                    "document_title": doc_title,
                    "section_id": section_id,
                    "section_heading": section_heading,
                    "pdf_page_number": pdf_page,
                    "section_preview_snippet": chunk_text[:150],  # S157: hover tooltip preview
                }
            )

    # S158: build TransparencyInfo for the retrieval transparency panel.
    # strategy_used is inferred from primary_strategy and retry state.
    # confidence_level is not known here (determined by _split_response after streaming);
    # stream_answer() fills it in before emitting the 'transparency' SSE event.
    primary_strategy = state.get("primary_strategy") or ""
    transparency_augmented = state.get("transparency_augmented", False)
    if transparency_augmented:
        strategy_used = "augmented_hybrid"
    elif primary_strategy == "graph_node":
        strategy_used = "graph_traversal"
    elif primary_strategy == "comparative_node":
        strategy_used = "comparative"
    else:
        strategy_used = "hybrid_retrieval"

    # Count unique sections across context chunks (using already-fetched chunk_meta).
    section_count = 0
    if chunks_dicts:
        section_count = len({meta[0] for meta in chunk_meta.values() if meta[0] is not None})

    transparency_info: TransparencyInfo = {
        "strategy_used": strategy_used,
        "chunk_count": len(chunks_dicts),
        "section_count": section_count,
        "augmented": transparency_augmented,
    }

    # Estimate retrieval confidence from chunk scores so confidence_gate_node
    # can make an informed routing decision.  Before this fix the gate always
    # saw the initial "low" default (synthesize_node prepares the prompt but
    # does not call the LLM, so LLM-derived confidence is not available yet).
    retrieval_confidence = "low"
    if chunks_dicts:
        scores = sorted(
            (c.get("score", 0) for c in chunks_dicts),
            reverse=True,
        )
        top3_avg = sum(scores[:3]) / min(len(scores), 3)
        # RRF with k=60: max score ~0.033 (rank 1 in both sources).
        # 0.025+ = strong matches in both sources; 0.015+ = decent single-source.
        if top3_avg >= 0.025:
            retrieval_confidence = "high"
        elif top3_avg >= 0.015:
            retrieval_confidence = "medium"

    # Return prompt fields for stream_answer() to call the LLM streaming directly.
    # This enables true token-by-token streaming: the first SSE token event is sent
    # as the LLM generates it, not after all tokens are buffered.
    return {
        "_llm_prompt": prompt,
        "_system_prompt": system_prompt,
        "confidence": retrieval_confidence,
        "source_citations": source_citations_out,
        "transparency": transparency_info,
    }


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
