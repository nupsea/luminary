"""comparative_node and its decomposition + per-side resolution helpers.

intent='comparative' path: ask the LLM to extract N subjects + topic,
resolve each subject to its document set (Kuzu entity match -> title
match), retrieve topic-focused chunks per side in parallel, then
round-robin interleave so no side dominates the context window.
Falls back to unfiltered retrieval if decomposition fails.
"""

import asyncio
import json
import logging

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import DocumentModel
from app.runtime.chat_nodes._shared import _chunk_to_dict, _round_robin
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

    decomposed = await _decompose_comparison(question)

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
        chunks = await retriever.retrieve(q, effective_doc_ids, k=10)
        interleaved = [_chunk_to_dict(c) for c in chunks]
    except Exception:
        logger.warning("comparative_node: fallback retrieval failed", exc_info=True)
        interleaved = []

    return {
        "chunks": interleaved,
        "section_context": f"Comparison query: {question}",
    }
