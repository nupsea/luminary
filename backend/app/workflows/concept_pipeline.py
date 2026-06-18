"""Concept-generation pipeline -- a sequential workflow of swappable nodes.

Each stage is one node fn per file in concept_nodes/, run in order over a shared
ConceptPipelineState; each is independently swappable/reorderable and emits diagnostics
(docs/concept-model-design.md §11-12). Persist runs only on a real run; --dry-run stops
before it so the output can be judged without touching the DB.

Build order (added incrementally):
    select_entities → embed_entities → cluster_subconcepts → rollup_themes
        → label → verify → build_lineage → [persist]
"""

from __future__ import annotations

import logging

from app.workflows.concept_nodes._shared import ConceptPipelineState, new_state
from app.workflows.concept_nodes.build_hierarchy import build_hierarchy
from app.workflows.concept_nodes.embed_entities import embed_entities
from app.workflows.concept_nodes.label_levels import label_levels
from app.workflows.concept_nodes.persist import persist_concepts
from app.workflows.concept_nodes.select_entities import select_entities

logger = logging.getLogger("concepts.pipeline")

# The ordered, swappable node sequence. persist_concepts no-ops on a dry run, so the
# dry-run report shows everything up to (not including) the DB write
# (docs/concept-model-design.md §11).
_NODES = [
    ("select_entities", select_entities),
    ("embed_entities", embed_entities),
    ("build_hierarchy", build_hierarchy),
    ("label_levels", label_levels),
    ("persist_concepts", persist_concepts),
]


async def run_pipeline(*, dry_run: bool, target_themes: int = 30) -> ConceptPipelineState:
    """Run the node sequence in order; returns the final state (with full diagnostics).

    A plain sequential runner over the _NODES list -- each node is a swappable unit that
    reads/writes the shared state. (Kept deliberately simple over a StateGraph: the flow
    is linear, and a single mutable state is the most inspectable + reorderable form.)
    """
    state = new_state(dry_run=dry_run, target_themes=target_themes)
    for name, node in _NODES:
        logger.debug("running node: %s", name)
        state = await node(state)
    return state
