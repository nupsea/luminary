"""label_levels node -- name each tier bottom-up (docs/concept-model-design.md §5).

- concept (level 2): label = its sun (medoid) -- cheap, no LLM, and already meaningful
  ("spark sql", "iceberg catalog").
- constellation (level 1): LLM names the theme from its concepts' suns + entities.
- galaxy (level 0): LLM names the broad domain from its constellation labels.

Bounded cost (~constellations + galaxies LLM calls, not ~concepts), throttled by a
semaphore, with a most-salient-member fallback when the model is unavailable. Model
routing (fast vs reasoning) is a future config knob; today it uses the default LLM.
"""

from __future__ import annotations

import asyncio

from app.services.llm import get_llm_service
from app.workflows.concept_nodes._shared import ConceptPipelineState, record

_CONCURRENCY = 3
_MAX_LABEL_LEN = 60

_CONSTELLATION_SYS = (
    "You are given key terms from one cluster of study material. Reply with a 2-4 word "
    "topic name capturing their common theme (e.g. 'Iceberg Table Format', 'OAuth & "
    "Sessions'). Name only -- no quotes, punctuation, or explanation."
)
_GALAXY_SYS = (
    "You are given the sub-topics of one broad area of study. Reply with a 2-3 word "
    "domain name (e.g. 'Data Engineering', 'Distributed Systems', 'Philosophy'). "
    "Name only -- no quotes, punctuation, or explanation."
)


def _clean(raw: str, fallback: str) -> str:
    name = (raw or "").strip().split("\n")[0].strip().strip('"').strip()[:_MAX_LABEL_LEN]
    return name or fallback


async def label_levels(state: ConceptPipelineState) -> ConceptPipelineState:
    h = state.get("hierarchy")
    if not h or not h.get("concepts"):
        record(state, "label_levels", {"named": 0})
        return state

    concepts, constellations, galaxies = h["concepts"], h["constellations"], h["galaxies"]

    # level 2: the sun is the label (no LLM)
    for c in concepts:
        c["label"] = c["sun"]

    llm = get_llm_service()
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _name(node: dict, system: str, terms: list[str], fallback: str) -> None:
        async with sem:
            try:
                raw = await llm.complete(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": ", ".join(terms[:14])},
                    ],
                    temperature=0.0,
                )
                node["label"] = _clean(raw, fallback)
            except Exception:
                node["label"] = fallback

    # level 1: constellations, named from their concepts' suns + a few member entities
    con_tasks = []
    for con in constellations:
        suns = [concepts[ci]["sun"] for ci in con["concept_idxs"]]
        terms = suns + con["entities"][:6]
        fallback = suns[0] if suns else (con["entities"][0] if con["entities"] else "Theme")
        con_tasks.append(_name(con, _CONSTELLATION_SYS, terms, fallback))
    await asyncio.gather(*con_tasks)

    # level 0: galaxies, named from their constellation labels
    gal_tasks = []
    for gal in galaxies:
        con_labels = [constellations[i]["label"] for i in gal["constellation_idxs"]]
        fallback = con_labels[0] if con_labels else (gal["entities"] or ["Domain"])[0]
        gal_tasks.append(_name(gal, _GALAXY_SYS, con_labels + gal["entities"][:4], fallback))
    await asyncio.gather(*gal_tasks)

    record(
        state,
        "label_levels",
        {
            "concepts_named": len(concepts),
            "constellations_named": len(constellations),
            "galaxies_named": len(galaxies),
            "galaxy_labels": [g["label"] for g in galaxies],
            "constellation_labels": [c["label"] for c in constellations][:20],
        },
    )
    return state
