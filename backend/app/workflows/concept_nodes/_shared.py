"""Shared state, diagnostics, and config for the concept-generation pipeline.

The pipeline is a sequential workflow of swappable nodes (docs/concept-model-design.md
§11). Every node reads/writes `ConceptPipelineState` and appends a structured block to
`state["diagnostics"]` so a run is fully inspectable (--dry-run dumps it). Each stage can
be evaluated, replaced, or A/B'd in isolation -- the point is to explore Lumen's reasoning.
"""

from __future__ import annotations

import logging
import re
from typing import Any, TypedDict

logger = logging.getLogger("concepts.pipeline")

# zero-width + control chars that pollute GLiNER surface forms (e.g. ZWSP + "\nredis").
# Escaped (not literal) so the source stays clean: ZWSP/ZWNJ/ZWJ/BOM + C0 controls.
_ZERO_WIDTH = "".join(chr(c) for c in (0x200B, 0x200C, 0x200D, 0xFEFF))
_JUNK_CHARS = re.compile(f"[{_ZERO_WIDTH}\x00-\x1f]+")


def clean_name(raw: str) -> str:
    """Normalize an entity surface form: strip zero-width/control chars, collapse space."""
    return re.sub(r"\s+", " ", _JUNK_CHARS.sub(" ", raw or "")).strip()

# --- entity-type policy (relevance lever 1; docs/concept-model-design.md §2) ---
# Concept-bearing types we keep as concept seeds.
CONCEPT_TYPES: frozenset[str] = frozenset(
    {
        "CONCEPT",
        "TECHNOLOGY",
        "LIBRARY",
        "DESIGN_PATTERN",
        "ALGORITHM",
        "DATA_STRUCTURE",
        "PROTOCOL",
        "API_ENDPOINT",
    }
)
# Named-entity noise dropped by default (a history corpus might re-include PERSON/EVENT).
NOISE_TYPES: frozenset[str] = frozenset({"PERSON", "ORGANIZATION", "PLACE", "DATE", "EVENT"})

MIN_FREQUENCY = 2          # drop hapax entities
MIN_ENTITY_LEN = 3
MIN_DOC_ENTITIES = 3       # below this a doc's entities form a single sub-concept


PIPELINE_CONFIG = {
    # dendrogram cut heights (cosine distance) for the nested Universe (§0):
    # galaxy (domain) merges far apart; concept (solar system) merges close.
    "galaxy_distance": 0.78,
    "constellation_distance": 0.60,
    "concept_distance": 0.38,
    "max_concepts_cap": 400,            # safety cap on studyable (level-2) concepts
    "lateral_edge_min_sim": 0.45,       # min cosine sim to draw an intra-constellation link
    # legacy 2-level knobs (superseded by the dendrogram; kept for the old path):
    "target_themes_cap": 30,
    "subconcept_cosine_threshold": 0.45,
    "theme_cosine_threshold": 0.55,
}

# concept hierarchy levels
LEVEL_GALAXY = 0
LEVEL_CONSTELLATION = 1
LEVEL_CONCEPT = 2


class EntityRec(TypedDict):
    name: str
    type: str
    frequency: int
    document_ids: list[str]


class ConceptPipelineState(TypedDict, total=False):
    """Flows through the nodes. `total=False` -- each node fills its slice."""

    dry_run: bool
    target_themes: int
    # select_entities -> :
    entities: list[EntityRec]            # kept, deduped across docs
    per_doc_entities: dict[str, list[str]]   # doc_id -> kept entity names
    # embed_entities -> :
    vectors: dict[str, list[float]]      # entity name -> embedding
    # cluster_subconcepts -> :
    subconcepts: list[dict]              # {label?, entities, document_ids, centroid, salience}
    # rollup_themes -> :
    themes: list[dict]                   # {label?, sub_idxs, entities, document_ids, centroid, ...}
    theme_edges: list[tuple[int, int]]
    # observability:
    diagnostics: dict[str, Any]


def new_state(dry_run: bool, target_themes: int) -> ConceptPipelineState:
    return ConceptPipelineState(
        dry_run=dry_run, target_themes=target_themes, diagnostics={}
    )


def record(state: ConceptPipelineState, node: str, payload: dict[str, Any]) -> None:
    """Attach a node's structured diagnostics + log a one-line summary."""
    state.setdefault("diagnostics", {})[node] = payload
    summary = " · ".join(f"{k}={v}" for k, v in payload.items() if not isinstance(v, list | dict))
    logger.info("[%s] %s", node, summary)
