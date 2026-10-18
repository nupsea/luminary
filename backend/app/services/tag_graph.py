"""Tag co-occurrence graph service

Computes a tag co-occurrence network from NoteTagIndexModel data.
Exposes an in-memory cache that is invalidated whenever _sync_tag_index writes.

Co-occurrence: two tags A and B co-occur when they appear together on the same note.
Edge weight = number of notes they share.

Cache TTL: 60 seconds (stale only if notes are written externally, bypassing the
invalidation hook in _sync_tag_index). The TTL is a safety net, not the primary
invalidation mechanism.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos.tag_repo import TagRepo

logger = logging.getLogger(__name__)


@dataclass
class TagNodeOut:
    id: str
    display_name: str
    parent_tag: str | None
    usage_count: int


@dataclass
class TagEdgeOut:
    tag_a: str
    tag_b: str
    weight: int


@dataclass
class TagGraphOut:
    nodes: list[TagNodeOut]
    edges: list[TagEdgeOut]
    generated_at: float  # unix timestamp


# In-memory cache

_CACHE_TTL = 60.0  # seconds

_cache: dict = {}  # keys: "graph" -> TagGraphOut, "ts" -> float (monotonic)


def invalidate_tag_graph_cache() -> None:
    """Clear the in-memory graph cache.

    Called by _sync_tag_index whenever tag index data changes so that the
    next GET /tags/graph request rebuilds from fresh data.
    """
    _cache.clear()
    logger.debug("Tag graph cache invalidated")


def _is_cache_fresh() -> bool:
    if "graph" not in _cache:
        return False
    return time.monotonic() - _cache.get("ts", 0.0) < _CACHE_TTL


def get_cached_graph() -> TagGraphOut | None:
    """Return cached graph if still fresh, else None."""
    if _is_cache_fresh():
        return _cache.get("graph")
    return None


MAX_NODES = 200
MAX_EDGES = 500
MIN_EDGE_WEIGHT = 2


async def build_tag_graph(session: AsyncSession) -> TagGraphOut:
    """Build the tag co-occurrence graph.

    Algorithm:
    1. Fetch top-200 canonical tags by usage_count as the node set.
    2. Self-join note_tag_index to compute co-occurrence weights.
    3. Filter: weight >= 2, both endpoints in node set, take top-500 by weight.
    4. Cache result and return.

    The result is cached in memory. The cache is invalidated on every
    _sync_tag_index write (note create/update/delete/merge).
    """
    cached = get_cached_graph()
    if cached is not None:
        return cached

    # 1. Top-200 canonical tags by usage_count
    tags = TagRepo(session)
    node_rows = await tags.most_used(MAX_NODES)
    node_set: set[str] = {row[0] for row in node_rows}
    nodes: list[TagNodeOut] = [
        TagNodeOut(id=row[0], display_name=row[1], parent_tag=row[2], usage_count=row[3])
        for row in node_rows
    ]

    if not node_set:
        result = TagGraphOut(nodes=[], edges=[], generated_at=time.time())
        _cache["graph"] = result
        _cache["ts"] = time.monotonic()
        return result

    # 2. Co-occurrence edges via self-join on note_tag_index
    # a.tag_full < b.tag_full ensures each pair appears once (no duplicates, no self-loops)
    edge_rows = await tags.note_co_occurrence(MIN_EDGE_WEIGHT, MAX_EDGES)

    # 3. Filter edges where both endpoints are in the node set
    edges: list[TagEdgeOut] = [
        TagEdgeOut(tag_a=row[0], tag_b=row[1], weight=int(row[2]))
        for row in edge_rows
        if row[0] in node_set and row[1] in node_set
    ]

    result = TagGraphOut(nodes=nodes, edges=edges, generated_at=time.time())
    _cache["graph"] = result
    _cache["ts"] = time.monotonic()

    logger.info(
        "Tag graph built: %d nodes, %d edges (after node-set filter)",
        len(nodes),
        len(edges),
    )
    return result
