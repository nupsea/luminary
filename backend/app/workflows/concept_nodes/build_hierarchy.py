"""build_hierarchy node -- group entity seeds into studyable concepts (concept-model-design.md §0).

One average-linkage cosine dendrogram over the concept seeds, cut once into concepts
(solar systems). Each concept has a "sun" (medoid). Concepts then link to their nearest
neighbours (k-NN, semantic distance with a cutoff) -- these RELATED_TO edges drive grounding
and "related concepts". A verify/dedup pass collapses near-identical concepts so one idea is
one node.

This produces a FLAT concept layer -- the old galaxy/constellation tiers (the Knowledge
Universe sky) were removed; nothing read them once the Universe surface was retired. Heavy
compute (linkage) runs in a thread; everything is logged so the result is judged on real
data via --dry-run.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.workflows.concept_nodes._shared import (
    LEVEL_CONCEPT,
    PIPELINE_CONFIG,
    ConceptPipelineState,
    record,
)


def _cut_concepts(vectors: list[list[float]], concept_cap: int) -> list[int]:
    """Average-linkage cosine tree, cut to a target concept COUNT via maxclust.

    Gap/percentile height cuts are pathological on bge-small (an outlier dominates the top
    of the tree), so maxclust cuts to a target count instead (~1 concept / 4 entities,
    clamped to the cap). The *groupings* still emerge from the data; only the count is bounded.
    """
    import numpy as np  # noqa: PLC0415
    from scipy.cluster.hierarchy import fcluster, linkage  # noqa: PLC0415
    from scipy.spatial.distance import pdist  # noqa: PLC0415

    arr = np.array(vectors, dtype="float32")
    z = linkage(pdist(arr, metric="cosine"), method="average")
    n = len(vectors)
    tp = int(max(1, min(concept_cap, round(n / 4))))
    return [int(x) for x in fcluster(z, t=min(tp, n), criterion="maxclust")]


def _centroid(vectors: list[list[float]]) -> list[float]:
    import numpy as np  # noqa: PLC0415

    return np.mean(np.array(vectors, dtype="float32"), axis=0).astype("float32").tolist()


def _cos(a: list[float], b: list[float]) -> float:
    import numpy as np  # noqa: PLC0415

    va, vb = np.array(a, dtype="float32"), np.array(b, dtype="float32")
    return float(va @ vb / ((np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-9))


def _knn_edges(
    centroids: list[list[float]], cutoff: float, top_k: int
) -> list[tuple[int, int, float]]:
    """Sparse similarity edges: each node -> its top-K neighbours above the cutoff.

    One matrix multiply for all pairwise cosines (fast), then keep top-K per node and
    dedupe to an undirected edge list. Avoids the all-pairs hairball + slow persist.
    """
    import numpy as np  # noqa: PLC0415

    n = len(centroids)
    if n < 2:
        return []
    c = np.array(centroids, dtype="float32")
    c = c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)
    sims = c @ c.T
    np.fill_diagonal(sims, -1.0)
    k = max(1, min(top_k, n - 1))
    edges: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in np.argsort(-sims[i])[:k]:
            s = float(sims[i, j])
            if s < cutoff:
                break
            a, b = (i, int(j)) if i < j else (int(j), i)
            edges[(a, b)] = round(s, 3)
    return [(a, b, w) for (a, b), w in edges.items()]


def _dedup_concepts(concepts: list[dict], cutoff: float) -> tuple[list[dict], int]:
    """The verify/dedup step (knowledge-model.md §7): collapse near-identical level-2 concepts.

    Two solar systems whose centroids are essentially the same idea become one node, so an idea
    is one concept (and clicking it anywhere lands on the same node). Conservative by design --
    a high cosine cutoff, under-claim over mislabel. Union-find on the centroid-similarity matrix.
    Runs BEFORE tier assembly + edge build so all downstream indices stay consistent.
    """
    import numpy as np  # noqa: PLC0415

    n = len(concepts)
    if n < 2:
        return concepts, 0
    cen = np.array([c["centroid"] for c in concepts], dtype="float32")
    cen = cen / (np.linalg.norm(cen, axis=1, keepdims=True) + 1e-9)
    sims = cen @ cen.T

    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            if float(sims[i, j]) >= cutoff:
                _union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[_find(i)].append(i)
    if len(groups) == n:
        return concepts, 0

    merged: list[dict] = []
    for idxs in groups.values():
        if len(idxs) == 1:
            merged.append(concepts[idxs[0]])
            continue
        # the most-salient member keeps identity (sun, constellation/galaxy); the rest fold in
        head = max(idxs, key=lambda i: concepts[i]["salience"])
        merged.append(
            {
                **concepts[head],
                "entities": sorted({e for i in idxs for e in concepts[i]["entities"]}),
                "document_ids": sorted({d for i in idxs for d in concepts[i]["document_ids"]}),
                "salience": float(sum(concepts[i]["salience"] for i in idxs)),
                "centroid": _centroid([concepts[i]["centroid"] for i in idxs]),
            }
        )
    return merged, n - len(merged)


async def build_hierarchy(state: ConceptPipelineState) -> ConceptPipelineState:
    entities = state.get("entities", [])
    vec_of = state.get("vectors", {})
    rec_of = {e["name"]: e for e in entities}
    names = [e["name"] for e in entities if e["name"] in vec_of]

    if len(names) < 3:
        state["hierarchy"] = {"concepts": []}
        state["lateral_edges"] = []
        record(state, "build_hierarchy", {"concepts": 0})
        return state

    cfg = PIPELINE_CONFIG
    vectors = [vec_of[n] for n in names]
    cpt_l = await asyncio.to_thread(_cut_concepts, vectors, cfg["max_concepts_cap"])

    by_concept: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(cpt_l):
        by_concept[c].append(i)

    def _freq(name: str) -> int:
        return int(rec_of.get(name, {}).get("frequency", 1))

    def _docs(idxs: list[int]) -> list[str]:
        out: set[str] = set()
        for i in idxs:
            out.update(rec_of.get(names[i], {}).get("document_ids", []))
        return sorted(out)

    # concepts (solar systems): each cluster of entities, sun = medoid (most central member)
    concepts: list[dict] = []
    for idxs in by_concept.values():
        ents = [names[i] for i in idxs]
        cen = _centroid([vectors[i] for i in idxs])
        sun = max(ents, key=lambda n: _cos(vec_of[n], cen))
        concepts.append(
            {
                "level": LEVEL_CONCEPT, "label": "", "sun": sun, "entities": sorted(ents),
                "centroid": cen,
                "salience": float(sum(_freq(n) for n in ents)),
                "document_ids": _docs(idxs),
            }
        )

    # safety cap: keep the most salient concepts
    if len(concepts) > cfg["max_concepts_cap"]:
        concepts.sort(key=lambda c: c["salience"], reverse=True)
        concepts = concepts[: cfg["max_concepts_cap"]]

    # verify/dedup: one idea -> one node, before edges are built off these indices
    concepts, n_deduped = _dedup_concepts(concepts, cfg["concept_dedup_cutoff"])

    # RELATED_TO edges follow semantic distance, SPARSIFIED to a k-NN graph: each concept
    # links to its top-K nearest neighbours above the cutoff (close strong, related-distant
    # thin, unrelated none). All-pairs-above-cutoff exploded to ~75k edges on bge-small.
    lateral = _knn_edges(
        [c["centroid"] for c in concepts],
        cfg["concept_edge_cutoff"], cfg["concept_edge_top_k"],
    )

    state["hierarchy"] = {"concepts": concepts}
    state["lateral_edges"] = lateral

    record(
        state,
        "build_hierarchy",
        {
            "concepts": len(concepts),
            "deduped": n_deduped,
            "lateral_edges": len(lateral),
            "concept_sample": [
                {"sun": c["sun"], "members": c["entities"][:8]}
                for c in sorted(concepts, key=lambda x: -x["salience"])[:20]
            ],
        },
    )
    return state
