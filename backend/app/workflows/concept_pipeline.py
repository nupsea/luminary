"""Concept-generation pipeline -- a LangGraph StateGraph of swappable nodes.

Mirrors the ingestion workflow pattern (StateGraph + one node fn per file in
concept_nodes/). Nodes are added here in order; each is independently swappable and
emits diagnostics (docs/concept-model-design.md §11-12). Persist is appended only for a
real run; --dry-run stops before it so the output can be judged without touching the DB.

Build order (added incrementally):
    select_entities → embed_entities → cluster_subconcepts → rollup_themes
        → label → verify → build_lineage → [persist]
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.workflows.concept_nodes._shared import ConceptPipelineState, new_state
from app.workflows.concept_nodes.cluster_subconcepts import cluster_subconcepts
from app.workflows.concept_nodes.embed_entities import embed_entities
from app.workflows.concept_nodes.rollup_themes import rollup_themes
from app.workflows.concept_nodes.select_entities import select_entities

logger = logging.getLogger("concepts.pipeline")

# The ordered, swappable node sequence. Append nodes here as they land; the dry-run
# runs every node except persist.
_NODES = [
    ("select_entities", select_entities),
    ("embed_entities", embed_entities),
    ("cluster_subconcepts", cluster_subconcepts),
    ("rollup_themes", rollup_themes),
    # ("label", label_themes),
    # ("verify", verify_themes),
    # ("build_lineage", build_lineage),
]


def build_pipeline(persist: bool = False):
    """Compile the StateGraph from the node sequence (+ persist when not a dry run)."""
    builder: StateGraph = StateGraph(ConceptPipelineState)
    names = [n for n, _ in _NODES]
    for name, fn in _NODES:
        builder.add_node(name, fn)
    # (persist node appended here once built, gated on `persist`)
    builder.add_edge(START, names[0])
    for a, b in zip(names, names[1:], strict=False):
        builder.add_edge(a, b)
    builder.add_edge(names[-1], END)
    return builder.compile()


async def run_pipeline(*, dry_run: bool, target_themes: int = 30) -> ConceptPipelineState:
    """Run the pipeline; returns the final state (with full diagnostics)."""
    graph = build_pipeline(persist=not dry_run)
    state = new_state(dry_run=dry_run, target_themes=target_themes)
    result: ConceptPipelineState = await graph.ainvoke(state)
    return result
