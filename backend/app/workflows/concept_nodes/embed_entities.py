"""embed_entities node -- vectorize concept seeds for clustering.

Baseline: embed the (cleaned) entity surface form with bge-small (384-dim). Swappable
for context-centroid embeddings (mean of the chunk vectors where the entity occurs) once
the entity->chunk index exists -- that's the documented upgrade (docs/concept-model-design.md §3).
Logged `method` makes the choice explicit per run.
"""

from __future__ import annotations

import asyncio

from app.services.embedder import get_embedding_service
from app.workflows.concept_nodes._shared import ConceptPipelineState, record


async def embed_entities(state: ConceptPipelineState) -> ConceptPipelineState:
    names = [e["name"] for e in state.get("entities", [])]
    if not names:
        state["vectors"] = {}
        record(state, "embed_entities", {"embedded": 0, "method": "entity_name"})
        return state
    vectors = await asyncio.to_thread(get_embedding_service().encode, names)
    state["vectors"] = dict(zip(names, vectors, strict=True))
    record(
        state,
        "embed_entities",
        {"embedded": len(names), "dim": len(vectors[0]) if vectors else 0, "method": "entity_name"},
    )
    return state
