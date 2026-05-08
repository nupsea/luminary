"""graph_node and its entity-extraction / Kuzu-query helpers.

intent='relational' path: extract entity names from the question, query
Kuzu's CO_OCCURS + RELATED_TO edges, and run hybrid retrieval (k=5) as a
grounding supplement. Falls through to search (intent='factual') on
Kuzu failure or 0 results.
"""

import logging
import re

from app.services.retriever import get_retriever
from app.types import ChatState, ScoredChunk

logger = logging.getLogger(__name__)


_ENTITY_RE = re.compile(r'["\']([^"\']{2,})["\']')
_CAPITALIZED_RE = re.compile(r"\b([A-Z][a-zA-Z]{2,})\b")


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
        len(entity_names),
        len(graph_lines),
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
