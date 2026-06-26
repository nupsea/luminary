"""select_entities node -- relevance lever 1 (docs/concept-model-design.md §2).

Gathers entities from the graph and keeps only concept-bearing ones: drops the NER
noise (PERSON / ORGANIZATION / PLACE / DATE / EVENT) and hapax mentions. This is the
deterministic step that stops "Iranian artists" from becoming a theme. Emits a full
kept/dropped breakdown so the filter can be judged on real data via --dry-run.

Swappable: the type policy + frequency floor live in _shared (CONCEPT_TYPES / NOISE_TYPES
/ MIN_FREQUENCY) so a different corpus can re-tune without touching this node.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from app.services.graph import get_graph_service
from app.workflows.concept_nodes._shared import (
    CONCEPT_TYPES,
    MIN_ENTITY_LEN,
    MIN_FREQUENCY,
    ConceptPipelineState,
    EntityRec,
    clean_name,
    is_junk_entity,
    record,
)


def _gather() -> tuple[dict[str, EntityRec], dict[str, list[dict]]]:
    """Synchronous graph read (run off the loop). Returns (by_name, raw_per_doc)."""
    graph = get_graph_service()
    by_name: dict[str, EntityRec] = {}
    raw_per_doc: dict[str, list[dict]] = {}
    for doc_id in graph.get_all_document_ids():
        recs = graph.get_entities_detailed_for_document(doc_id)
        for r in recs:
            r["name"] = clean_name(r.get("name", ""))
        raw_per_doc[doc_id] = recs
        for r in recs:
            name = r["name"]
            if not name:
                continue
            rec = by_name.get(name)
            if rec is None:
                by_name[name] = EntityRec(
                    name=name, type=r.get("type", ""), frequency=int(r.get("frequency", 1)),
                    document_ids=[doc_id],
                )
            else:
                rec["frequency"] += int(r.get("frequency", 1))
                if doc_id not in rec["document_ids"]:
                    rec["document_ids"].append(doc_id)
    return by_name, raw_per_doc


async def select_entities(state: ConceptPipelineState) -> ConceptPipelineState:
    by_name, raw_per_doc = await asyncio.to_thread(_gather)

    dropped: Counter = Counter()           # reason -> count
    dropped_types: Counter = Counter()     # entity type -> count (for the noise breakdown)
    kept: dict[str, EntityRec] = {}
    for name, rec in by_name.items():
        etype = rec["type"]
        if len(name) < MIN_ENTITY_LEN:
            dropped["short_name"] += 1
        elif etype not in CONCEPT_TYPES:
            dropped["non_concept_type"] += 1
            dropped_types[etype] += 1
        elif rec["frequency"] < MIN_FREQUENCY:
            dropped["below_freq_floor"] += 1
        elif is_junk_entity(name):
            dropped["junk"] += 1
        else:
            kept[name] = rec

    kept_names = set(kept)
    per_doc = {
        doc_id: sorted(n for n in {r.get("name", "").strip() for r in recs} if n in kept_names)
        for doc_id, recs in raw_per_doc.items()
    }
    per_doc = {d: names for d, names in per_doc.items() if names}

    state["entities"] = sorted(kept.values(), key=lambda r: (-r["frequency"], r["name"]))
    state["per_doc_entities"] = per_doc

    kept_by_type = Counter(r["type"] for r in kept.values())
    record(
        state,
        "select_entities",
        {
            "documents": len(raw_per_doc),
            "entities_seen": len(by_name),
            "entities_kept": len(kept),
            "dropped_total": sum(dropped.values()),
            "dropped_by_reason": dict(dropped),
            "dropped_noise_types": dict(dropped_types.most_common()),
            "kept_by_type": dict(kept_by_type.most_common()),
            "top_kept": [
                f"{r['name']}({r['type']},f{r['frequency']})" for r in state["entities"][:25]
            ],
        },
    )
    return state
