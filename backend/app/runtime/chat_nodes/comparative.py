"""comparative_node and its decomposition + per-side resolution helpers.

intent='comparative' path: ask the LLM to extract N subjects + topic,
resolve each subject to its document set (Kuzu entity match -> title
match), retrieve topic-focused chunks per side in parallel with the same
rerank setting search_node uses, then round-robin interleave so no side
dominates the context window. Falls back to unfiltered retrieval if
decomposition fails.
"""

import asyncio
import json
import logging
import time

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import DocumentModel
from app.runtime.chat_nodes._shared import _chunk_to_dict, _read_rerank_enabled, _round_robin
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services.llm import get_llm_service
from app.services.retriever import get_retriever
from app.types import ChatState

logger = logging.getLogger(__name__)


async def _decompose_comparison(question: str) -> dict | None:
    """LLM-decompose a comparison question into N sides and a topic.

    Returns {"sides": [list of subject names], "topic": str} or None on failure.
    Handles 2-way, 3-way, and any N-way comparisons.
    """
    try:
        text = (
            await get_llm_service().complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract ALL subjects being compared and the comparison topic. "
                            "Reply with exactly this JSON (no prose, no markdown): "
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
        ).strip()
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


async def _resolve_side_to_docs(side_name: str, scope_doc_ids: list[str] | None) -> list[str]:
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

        conn = _graph_module.get_graph_service()._conn
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
        logger.warning("_resolve_side_to_docs: Kuzu lookup failed for %r", side_name, exc_info=True)

    # Document title search — catches cases where the side name appears in a title
    try:

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
    rerank = await _read_rerank_enabled(logger, "comparative_node")

    # Sequential LLM call before any retrieval starts -- on a small local model
    # this alone can be a double-digit-second cost that never shows up in the
    # UI's "first token" figure, which times only the final-answer LLM call
    # (qa.py's t_llm), not this decomposition call or the retrieval below.
    t_decompose = time.perf_counter()
    decomposed = await _decompose_comparison(question)
    logger.info(
        "[perf] comparative_node: decomposition took %.2fs (matched=%s)",
        time.perf_counter() - t_decompose,
        bool(decomposed),
    )

    if decomposed:
        sides: list[str] = decomposed["sides"]
        topic: str = decomposed["topic"]

        logger.info(
            "comparative_node: %d sides=%s topic=%r",
            len(sides),
            sides,
            topic,
        )

        resolved: list[list[str]] = await asyncio.gather(
            *[_resolve_side_to_docs(side, effective_doc_ids) for side in sides]
        )

        k_per_side = max(4, 12 // len(sides))
        # Overfetch so a global dedup pass (below) still leaves each side its
        # full quota. Sides that share a document -- the common case when a
        # subject is a concept rather than a document/author, so neither
        # resolves to a distinct doc set -- otherwise retrieve the same top
        # passages for both queries and the comparison has nothing to contrast
        # (I-55). This only asks the retriever to return more of the pool it
        # already ranked; it does not deepen the rerank candidate pool.
        fetch_k = min(k_per_side * 3, 20)

        async def _retrieve_for_side(side: str, side_docs: list[str]) -> list[dict]:
            # If no docs resolved for this side, widen the query to include the
            # subject name so unfiltered retrieval still finds relevant passages.
            query = topic if side_docs else f"{side} {topic}"
            filter_ids = side_docs or effective_doc_ids
            try:
                chunks = await retriever.retrieve(
                    query, filter_ids, k=fetch_k, rerank=rerank
                )
                return [_chunk_to_dict(c) for c in chunks]
            except Exception:
                logger.warning(
                    "comparative_node: retrieval failed for side %r", side, exc_info=True
                )
                return []

        t_retrieve = time.perf_counter()
        per_side_chunks_raw: list[list[dict]] = await asyncio.gather(
            *[_retrieve_for_side(side, docs) for side, docs in zip(sides, resolved, strict=True)]
        )
        logger.info(
            "[perf] comparative_node: %d-side retrieval took %.2fs (fetch_k=%d, rerank=%s)",
            len(sides),
            time.perf_counter() - t_retrieve,
            fetch_k,
            rerank,
        )

        # A chunk retrieved by an earlier side is not repeated for a later one:
        # each chunk_id is assigned to the first (highest-ranked-so-far) side
        # that surfaced it, and every side keeps filling from its own
        # overfetched pool up to k_per_side. Without this, two concepts that
        # live in the same passage of a small corpus get identical context on
        # both sides of the comparison and the model has nothing to compare.
        seen_chunk_ids: set[str] = set()
        per_side_chunks: list[list[dict]] = []
        duplicates_dropped = 0
        for side_chunks in per_side_chunks_raw:
            deduped: list[dict] = []
            for c in side_chunks:
                cid = c.get("chunk_id")
                if cid and cid in seen_chunk_ids:
                    duplicates_dropped += 1
                    continue
                if cid:
                    seen_chunk_ids.add(cid)
                deduped.append(c)
                if len(deduped) >= k_per_side:
                    break
            per_side_chunks.append(deduped)
        if duplicates_dropped:
            logger.info(
                "comparative_node: dropped %d cross-side duplicate chunk(s)",
                duplicates_dropped,
            )

        interleaved = _round_robin(per_side_chunks)

        side_labels = "; ".join(
            f"{side} ({len(docs)} doc(s))" for side, docs in zip(sides, resolved, strict=True)
        )
        section_context = f"Comparing: {side_labels} — topic: {topic}"

        for side, docs in zip(sides, resolved, strict=True):
            logger.info("comparative_node: side=%r resolved to %d doc(s)", side, len(docs))
        logger.info(
            "comparative_node: retrieving %d chunks per side, total=%d",
            k_per_side,
            len(interleaved),
        )
        return {"chunks": interleaved, "section_context": section_context}

    # Fallback: unfiltered retrieval when LLM decomposition fails
    logger.info("comparative_node: LLM decomposition failed — using unfiltered retrieval")
    try:
        chunks = await retriever.retrieve(q, effective_doc_ids, k=10, rerank=rerank)
        interleaved = [_chunk_to_dict(c) for c in chunks]
    except Exception:
        logger.warning("comparative_node: fallback retrieval failed", exc_info=True)
        interleaved = []

    return {
        "chunks": interleaved,
        "section_context": f"Comparison query: {question}",
    }
