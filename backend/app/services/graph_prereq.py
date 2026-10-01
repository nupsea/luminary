"""Prerequisite edges within a document, and the study path they imply.

Traversal runs here, not in SQL: a breadth-first walk from the start entity, then
Kahn's topological sort over what it reached.
"""

from __future__ import annotations

import logging
from collections import deque

from app.repos.graph_entity_repo import GraphEntityRepo
from app.types import LearningPathNode

logger = logging.getLogger(__name__)

_KIND = "PREREQUISITE_OF"


async def prerequisite_edges(repo: GraphEntityRepo, document_id: str) -> list[dict]:
    """[{from_entity, to_entity, from_id, to_id, confidence}] for one document."""
    return [
        {
            "from_entity": name_a,
            "to_entity": name_b,
            "from_id": id_a,
            "to_id": id_b,
            "confidence": float(edge.confidence or 1.0),
        }
        for name_a, name_b, id_a, id_b, edge in await repo.named_edges(document_id, _KIND)
    ]


async def entry_points(repo: GraphEntityRepo, document_id: str, limit: int) -> list[str]:
    """Entities that are a prerequisite of something and have none themselves,
    most mentioned first."""
    edges = await repo.edges_for_documents([document_id], (_KIND,))
    has_prereqs = {e.source_id for e in edges}
    referenced = {e.target_id for e in edges}
    entities = await repo.entities_for_document(document_id)
    entry = [e for e in entities if e.id in referenced and e.id not in has_prereqs]
    entry.sort(key=lambda e: e.mention_count, reverse=True)
    return [e.name for e in entry[:limit]]


def _empty_path(start_entity_name: str, document_id: str) -> dict:
    return {"start_entity": start_entity_name, "document_id": document_id, "nodes": [], "edges": []}


def _reachable(
    start_id: str, adj: dict[str, list[tuple[str, float]]]
) -> tuple[set[str], list[tuple[str, str, float]]]:
    nodes, edges = {start_id}, []
    queue: deque[str] = deque([start_id])
    while queue:
        current = queue.popleft()
        for neighbour, conf in adj.get(current, []):
            edges.append((current, neighbour, conf))
            if neighbour not in nodes:
                nodes.add(neighbour)
                queue.append(neighbour)
    return nodes, edges


def _topological_order(nodes: set[str], edges: list[tuple[str, str, float]]) -> list[str]:
    """Prerequisites first. Nodes on a cycle are left out."""
    in_degree = dict.fromkeys(nodes, 0)
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b, _ in edges:
        out[a].append(b)
        in_degree[b] += 1
    queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in out[node]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    order.reverse()
    return order


async def learning_path(repo: GraphEntityRepo, start_entity_name: str, document_id: str) -> dict:
    """The prerequisite chain below `start_entity_name`, in study order."""
    entities = {e.id: e for e in await repo.entities_for_document(document_id)}
    wanted = start_entity_name.lower()
    start_id = next((eid for eid, e in entities.items() if e.name.lower() == wanted), None)
    adj: dict[str, list[tuple[str, float]]] = {}
    for edge in await repo.edges_for_documents([document_id], (_KIND,)):
        adj.setdefault(edge.source_id, []).append((edge.target_id, float(edge.confidence or 1.0)))
    if start_id is None or start_id not in adj:
        return _empty_path(start_entity_name, document_id)

    nodes, edges = _reachable(start_id, adj)
    order = _topological_order(nodes, edges)
    if len(order) < len(nodes):
        logger.warning(
            "Cyclic PREREQUISITE_OF subgraph detected for document %s"
            " (start=%s): %d nodes unreachable via topological sort",
            document_id,
            start_entity_name,
            len(nodes) - len(order),
        )

    def name(eid: str) -> str:
        return entities[eid].name if eid in entities else eid

    return {
        "start_entity": start_entity_name,
        "document_id": document_id,
        "nodes": [
            LearningPathNode(
                entity_id=eid,
                name=entities[eid].name,
                entity_type=entities[eid].type or "CONCEPT",
                depth=depth,
            )
            for depth, eid in enumerate(order)
            if eid in entities
        ],
        "edges": [
            {"from_entity": name(a), "to_entity": name(b), "confidence": c} for a, b, c in edges
        ],
    }
