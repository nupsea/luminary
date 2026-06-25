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


# formula / latex / fragment markers, and ultra-generic abstract words that aren't
# studyable concepts (they blur to the embedding centre and vacuum up noise as "suns").
_MATHY = re.compile(r"[()\\=]|script(script)?style|divided by|\bd[xy]\b|\blim\b")
# Unicode Mathematical Alphanumeric Symbols (bold/italic/script): GLiNER sometimes lifts a
# styled run as a label (e.g. "𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐚𝐠𝐠𝐫𝐞𝐠𝐚𝐭𝐢𝐨𝐧 𝐥𝐚𝐲𝐞𝐫") -- never a real concept name.
_MATH_ALNUM = re.compile(r"[\U0001D400-\U0001D7FF]")
_GENERIC_STOP = frozenset(
    {
        "performance", "thought", "information", "intelligence", "approach",
        "proposed approach", "agreed", "affirmative", "affection", "for", "and",
        "advanced systems", "advanced technologies", "new technologies", "true powers",
        "critical information", "status information", "index information",
    }
)
# Source-code literals/keywords that surface as standalone "concepts" from code blocks but
# carry no studyable meaning on their own (boolean/null literals, type keywords).
_CODE_LITERALS = frozenset(
    {
        "false", "true", "null", "none", "nil", "nan", "void", "undefined",
        "dynamic", "static", "boolean", "int", "str", "char", "enum", "const",
    }
)


def is_junk_entity(name: str) -> bool:
    """Heuristic noise filter for NER surface forms that slipped past the type filter.

    Drops: pure numbers/symbols, digit-dominant strings, formula/latex fragments, unicode
    styled-text garbage, CLI flags (``--acl-spec``), snake_case code identifiers
    (``unique_files``), source-code literals (``false``), and a small stoplist of
    ultra-generic abstract words. Conservative -- format-driven.
    """
    n = name.strip().lower()
    if not n or n in _GENERIC_STOP or n in _CODE_LITERALS:
        return True
    if n.startswith("-"):            # CLI flag fragment, e.g. "--acl-spec"
        return True
    if "_" in n:                     # snake_case code identifier, e.g. "unique_files"
        return True
    if _MATH_ALNUM.search(name):     # unicode math-alphanumeric styled garbage
        return True
    letters = sum(c.isalpha() for c in n)
    digits = sum(c.isdigit() for c in n)
    if letters == 0 or digits > letters:
        return True
    return bool(_MATHY.search(n))

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


PIPELINE_CONFIG = {
    # Concepts are cut to a target COUNT (maxclust ~n/4 entities), adaptive to library size
    # and clamped to the cap. Height/gap cuts are pathological on bge-small (outliers dominate
    # the tree top). The groupings still emerge from the data; only the count is bounded.
    "concept_dedup_cutoff": 0.93,       # merge near-identical concepts (verify/dedup step)
    "max_concepts_cap": 400,            # cap on studyable concepts
    # edges: each concept links to its top-K nearest neighbours above a cutoff (k-NN graph,
    # not all-pairs -- all-pairs exploded to ~75k edges, a hairball + slow persist).
    "concept_edge_cutoff": 0.50,        # min centroid cosine for a concept<->concept link
    "concept_edge_top_k": 6,            # nearest neighbours kept per concept
}

# concept level (flat layer; 0/1 were the retired galaxy/constellation tiers)
LEVEL_CONCEPT = 2


class EntityRec(TypedDict):
    name: str
    type: str
    frequency: int
    document_ids: list[str]


class ConceptPipelineState(TypedDict, total=False):
    """Flows through the nodes. `total=False` -- each node fills its slice."""

    dry_run: bool
    # select_entities -> :
    entities: list[EntityRec]            # kept, deduped across docs
    per_doc_entities: dict[str, list[str]]   # doc_id -> kept entity names
    # embed_entities -> :
    vectors: dict[str, list[float]]      # entity name -> embedding
    # build_hierarchy -> : hierarchy {concepts}, lateral_edges
    # observability:
    diagnostics: dict[str, Any]


def new_state(dry_run: bool) -> ConceptPipelineState:
    return ConceptPipelineState(dry_run=dry_run, diagnostics={})


def record(state: ConceptPipelineState, node: str, payload: dict[str, Any]) -> None:
    """Attach a node's structured diagnostics + log a one-line summary."""
    state.setdefault("diagnostics", {})[node] = payload
    summary = " · ".join(f"{k}={v}" for k, v in payload.items() if not isinstance(v, list | dict))
    logger.info("[%s] %s", node, summary)
