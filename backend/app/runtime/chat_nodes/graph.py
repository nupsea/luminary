"""graph_node and its entity-extraction / Kuzu-query helpers.

intent='relational' path: extract entity names from the question, query
Kuzu's CO_OCCURS + RELATED_TO edges, and run hybrid retrieval (same depth +
rerank setting as search_node) as a grounding supplement. Falls through to
search (intent='factual') on Kuzu failure or 0 results.
"""

import logging
import re

from app.database import get_session_factory
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services.retriever import get_retriever
from app.services.settings_service import get_rerank_enabled
from app.types import ChatState, ScoredChunk

from ._shared import _chunk_to_dict

logger = logging.getLogger(__name__)


_ENTITY_RE = re.compile(r'["\']([^"\']{2,})["\']')
# A run of one or more capitalized words, e.g. "Inverted Index" or "Marie
# Curie" -- not just its first token. Matching only the first word of a
# multi-word proper noun sent Kuzu lookups for names that exist nowhere in
# the graph (I-55).
_CAPITALIZED_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})*\b")


def _extract_entities_from_question(question: str) -> list[str]:
    """Extract potential entity names from a question.

    Finds quoted strings first, then runs of capitalized words merged into a
    single phrase (skipping the question's own first word, which is
    capitalized because it opens the sentence, not because it names something).
    """
    entities: list[str] = []
    seen: set[str] = set()

    # Quoted strings
    for m in _ENTITY_RE.finditer(question):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            entities.append(name)

    # Capitalized phrases, skipping the sentence's own first word
    first_word, _, rest = question.partition(" ")
    for m in _CAPITALIZED_PHRASE_RE.finditer(rest):
        name = m.group(0).strip()
        if name and name not in seen:
            seen.add(name)
            entities.append(name)

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
        logger.warning("co-occurrence lookup failed for %s", name, exc_info=True)
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
        logger.warning("related-to lookup failed for %s", name, exc_info=True)
    return lines


async def graph_node(state: ChatState) -> dict:
    """Kuzu entity traversal for relational queries.

    Extracts entity names from the question, queries CO_OCCURS + RELATED_TO edges,
    and runs hybrid retrieval (same depth + rerank setting as search_node) as a
    grounding supplement. Falls through to search_node (via intent='factual') on
    Kuzu failure or 0 results.
    """
    question = state["question"]
    q = state.get("rewritten_question") or question
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None

    entity_names = _extract_entities_from_question(question)
    graph_lines: list[str] = []

    try:
        conn = _graph_module.get_graph_service()._conn
        for name in entity_names[:5]:  # cap at 5 entities
            graph_lines.extend(_query_kuzu_for_entity(conn, name))
    except Exception:
        logger.warning("graph_node: Kuzu query failed", exc_info=True)

    logger.info(
        "graph_node: extracted %d entities, got %d graph lines",
        len(entity_names),
        len(graph_lines),
    )

    if not graph_lines:
        logger.info("graph_node: no graph results — falling through to search")
        return {"intent": "factual"}

    section_context = "Knowledge graph connections:\n" + "\n".join(graph_lines)

    # Grounding supplement: same depth and rerank setting search_node uses.
    # A graph match (even a real one) says nothing about whether that entity's
    # co-occurrence neighbours are the passage that answers the question -- the
    # supplement is what actually has to carry the answer, so it must not be a
    # weaker retrieval than the search path gets (I-55).
    k = 6 if scope == "all" else 10
    try:
        async with get_session_factory()() as session:
            rerank = await get_rerank_enabled(session)
    except Exception as exc:
        logger.warning("graph_node: could not read rerank setting, defaulting off: %s", exc)
        rerank = False

    chunks_dicts: list[dict] = []
    try:
        retriever = get_retriever()
        chunks: list[ScoredChunk] = await retriever.retrieve(
            q, effective_doc_ids, k=k, rerank=rerank
        )
        chunks_dicts = [_chunk_to_dict(c) for c in chunks]
    except Exception:
        logger.warning("graph_node: retrieval failed", exc_info=True)

    return {
        "section_context": section_context,
        "chunks": chunks_dicts,
    }
