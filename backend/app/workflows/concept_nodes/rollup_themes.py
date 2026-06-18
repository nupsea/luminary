"""rollup_themes node -- roll sub-concepts up into cross-document themes.

Clusters sub-concept centroids by a cosine threshold (count = outcome, not input), then
caps by salience (coverage x breadth) for the Universe display. Lateral theme edges come
from shared documents. Swappable for LLM-grouping (docs/concept-model-design.md §4).
Emits each theme's member entities + doc-coverage so grouping quality is inspectable.
"""

from __future__ import annotations

import asyncio

from app.services.concept_extraction_service import _agglomerative, _centroid
from app.workflows.concept_nodes._shared import (
    PIPELINE_CONFIG,
    ConceptPipelineState,
    record,
)


async def rollup_themes(state: ConceptPipelineState) -> ConceptPipelineState:
    subs = state.get("subconcepts", [])
    if not subs:
        state["themes"] = []
        state["theme_edges"] = []
        record(state, "rollup_themes", {"themes": 0})
        return state

    threshold = PIPELINE_CONFIG["theme_cosine_threshold"]
    labels = await asyncio.to_thread(_agglomerative, [s["centroid"] for s in subs], None, threshold)
    members: dict[int, list[int]] = {}
    for si, lab in enumerate(labels):
        members.setdefault(lab, []).append(si)

    themes: list[dict] = []
    for sub_idxs in members.values():
        ents = sorted({e for si in sub_idxs for e in subs[si]["entities"]})
        docs = sorted({d for si in sub_idxs for d in subs[si]["document_ids"]})
        themes.append(
            {
                "sub_idxs": sub_idxs,
                "entities": ents,
                "document_ids": docs,
                "centroid": _centroid([subs[si]["centroid"] for si in sub_idxs]),
                "salience": float(len(docs)) * float(len(ents)),
            }
        )

    themes.sort(key=lambda t: t["salience"], reverse=True)
    cap = state.get("target_themes", PIPELINE_CONFIG["target_themes_cap"])
    themes = themes[:cap]

    edges: list[tuple[int, int]] = []
    for i in range(len(themes)):
        for j in range(i + 1, len(themes)):
            if set(themes[i]["document_ids"]) & set(themes[j]["document_ids"]):
                edges.append((i, j))

    state["themes"] = themes
    state["theme_edges"] = edges
    record(
        state,
        "rollup_themes",
        {
            "themes": len(themes),
            "edges": len(edges),
            "sample": [
                {"docs": len(t["document_ids"]), "n_entities": len(t["entities"]),
                 "members": t["entities"][:10]}
                for t in themes[:15]
            ],
        },
    )
    return state
