"""label_levels node -- name each concept (docs/concept-model-design.md §5).

A concept's label is its sun (medoid entity) -- cheap, no LLM, and already meaningful
("spark sql", "iceberg catalog"). The flat concept layer labels itself.
"""

from __future__ import annotations

from app.workflows.concept_nodes._shared import ConceptPipelineState, record


async def label_levels(state: ConceptPipelineState) -> ConceptPipelineState:
    h = state.get("hierarchy")
    concepts = (h or {}).get("concepts") or []
    for c in concepts:
        c["label"] = c["sun"]
    record(state, "label_levels", {"concepts_named": len(concepts)})
    return state
