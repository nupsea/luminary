"""cluster_subconcepts node -- group a document's entities into coherent sub-concepts.

Per-document agglomerative clustering by a cosine-distance *threshold* (not a forced
count): however many tight clusters genuinely cohere. Swappable for HDBSCAN / graph
community detection (docs/concept-model-design.md §4). Emits cluster sizes + samples so
the grouping can be judged before any LLM naming.
"""

from __future__ import annotations

import asyncio

from app.services.concept_extraction_service import _agglomerative, _centroid
from app.workflows.concept_nodes._shared import (
    MIN_DOC_ENTITIES,
    PIPELINE_CONFIG,
    ConceptPipelineState,
    record,
)


async def cluster_subconcepts(state: ConceptPipelineState) -> ConceptPipelineState:
    per_doc = state.get("per_doc_entities", {})
    vec_of = state.get("vectors", {})
    threshold = PIPELINE_CONFIG["subconcept_cosine_threshold"]

    subs: list[dict] = []
    for doc_id, doc_names in per_doc.items():
        names = [n for n in doc_names if n in vec_of]
        if not names:
            continue
        dv = [vec_of[n] for n in names]
        if len(names) < MIN_DOC_ENTITIES:
            groups = {0: list(range(len(names)))}
        else:
            labels = await asyncio.to_thread(_agglomerative, dv, None, threshold)
            groups = {}
            for i, lab in enumerate(labels):
                groups.setdefault(lab, []).append(i)
        for members in groups.values():
            ents = [names[i] for i in members]
            subs.append(
                {
                    "entities": ents,
                    "document_ids": [doc_id],
                    "centroid": _centroid([dv[i] for i in members]),
                    "salience": float(len(ents)),
                }
            )

    state["subconcepts"] = subs
    sizes = [len(s["entities"]) for s in subs]
    record(
        state,
        "cluster_subconcepts",
        {
            "subconcepts": len(subs),
            "avg_size": round(sum(sizes) / len(sizes), 1) if sizes else 0,
            "max_size": max(sizes, default=0),
            "sample": [
                s["entities"][:8]
                for s in sorted(subs, key=lambda x: -len(x["entities"]))[:12]
            ],
        },
    )
    return state
