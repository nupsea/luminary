"""build_hierarchy node -- the nested Universe (docs/concept-model-design.md §0).

One hierarchical-clustering dendrogram over the concept seeds, cut at three heights:
    galaxy (domain)  >  constellation (theme)  >  concept (solar system)
Galaxy/constellation cuts use the largest natural merge-height GAP within a bounded
cluster-count range (emergent few, not the 89-galaxy fragmentation a percentile gives);
concept uses a fine percentile cut. Same tree -> levels nest consistently. Each concept
has a "sun" (medoid). Edges follow semantic distance with a cutoff (no categorical walls):
concept<->concept across the graph + thin galaxy<->galaxy links between RELATED domains;
unrelated domains simply fall below the cutoff.

Replaces the flat cluster_subconcepts + rollup_themes path. Heavy compute (linkage) runs
in a thread; everything is logged so the structure is judged on real data via --dry-run.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.workflows.concept_nodes._shared import (
    LEVEL_CONCEPT,
    LEVEL_CONSTELLATION,
    LEVEL_GALAXY,
    PIPELINE_CONFIG,
    ConceptPipelineState,
    record,
)


def _cut_dendrogram(
    vectors: list[list[float]], galaxy_k: list[int], con_k: list[int], concept_cap: int
) -> tuple[list[int], list[int], list[int]]:
    """Single average-linkage cosine tree, cut to nested target COUNTS via maxclust.

    Gap/percentile height cuts are pathological on bge-small (an outlier dominates the
    top of the tree; domains separate at middle heights), giving either 89 or 2 galaxies.
    maxclust cuts to a target count (adaptive to library size, clamped sane) -- the
    *groupings* still emerge from the data, only the count is bounded; and maxclust is
    monotonic so galaxy < constellation < concept counts nest cleanly.
    """
    import numpy as np  # noqa: PLC0415
    from scipy.cluster.hierarchy import fcluster, linkage  # noqa: PLC0415
    from scipy.spatial.distance import pdist  # noqa: PLC0415

    arr = np.array(vectors, dtype="float32")
    z = linkage(pdist(arr, metric="cosine"), method="average")
    n = len(vectors)

    def _clamp(v: float, lo: int, hi: int) -> int:
        return int(max(lo, min(hi, round(v))))

    # ~1 galaxy / 200 entities, ~1 constellation / 45, ~1 concept / 4 -- clamped.
    tg = _clamp(n / 200, galaxy_k[0], galaxy_k[1])
    tc = max(_clamp(n / 45, con_k[0], con_k[1]), tg + 1)
    tp = max(_clamp(n / 4, tc + 1, concept_cap), tc + 1)

    def _mc(k: int) -> list[int]:
        return [int(x) for x in fcluster(z, t=min(k, n), criterion="maxclust")]

    return _mc(tg), _mc(tc), _mc(tp)


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


async def build_hierarchy(state: ConceptPipelineState) -> ConceptPipelineState:
    entities = state.get("entities", [])
    vec_of = state.get("vectors", {})
    rec_of = {e["name"]: e for e in entities}
    names = [e["name"] for e in entities if e["name"] in vec_of]

    empty = {"galaxies": [], "constellations": [], "concepts": []}
    if len(names) < 3:
        state["hierarchy"] = empty
        state["lateral_edges"] = []
        record(state, "build_hierarchy", {"galaxies": 0, "constellations": 0, "concepts": 0})
        return state

    cfg = PIPELINE_CONFIG
    vectors = [vec_of[n] for n in names]
    gal_l, con_l, cpt_l = await asyncio.to_thread(
        _cut_dendrogram, vectors, cfg["galaxy_k_range"],
        cfg["constellation_k_range"], cfg["max_concepts_cap"],
    )

    # group entity indices by the finest (concept) label; roll up to con/gal (nested)
    by_concept: dict[int, list[int]] = defaultdict(list)
    concept_con: dict[int, int] = {}
    concept_gal: dict[int, int] = {}
    for i, c in enumerate(cpt_l):
        by_concept[c].append(i)
        concept_con[c] = con_l[i]
        concept_gal[c] = gal_l[i]

    def _freq(name: str) -> int:
        return int(rec_of.get(name, {}).get("frequency", 1))

    def _docs(idxs: list[int]) -> list[str]:
        out: set[str] = set()
        for i in idxs:
            out.update(rec_of.get(names[i], {}).get("document_ids", []))
        return sorted(out)

    # level 2: concepts (solar systems)
    concepts: list[dict] = []
    concept_label_to_idx: dict[int, int] = {}
    for clabel, idxs in by_concept.items():
        ents = [names[i] for i in idxs]
        cen = _centroid([vectors[i] for i in idxs])
        # sun = medoid (most central member), not most-frequent
        sun = max(ents, key=lambda n: _cos(vec_of[n], cen))
        concepts.append(
            {
                "level": LEVEL_CONCEPT, "label": "", "sun": sun, "entities": sorted(ents),
                "centroid": cen,
                "salience": float(sum(_freq(n) for n in ents)),
                "document_ids": _docs(idxs),
                "_con": concept_con[clabel], "_gal": concept_gal[clabel],
            }
        )
        concept_label_to_idx[clabel] = len(concepts) - 1

    # safety cap: keep the most salient concepts
    if len(concepts) > cfg["max_concepts_cap"]:
        concepts.sort(key=lambda c: c["salience"], reverse=True)
        concepts = concepts[: cfg["max_concepts_cap"]]

    # level 1: constellations (group concepts by their constellation label)
    con_groups: dict[int, list[int]] = defaultdict(list)
    for ci, c in enumerate(concepts):
        con_groups[c["_con"]].append(ci)
    constellations: list[dict] = []
    con_label_to_idx: dict[int, int] = {}
    for clabel, cidxs in con_groups.items():
        ents = sorted({e for ci in cidxs for e in concepts[ci]["entities"]})
        constellations.append(
            {
                "level": LEVEL_CONSTELLATION, "label": "", "concept_idxs": cidxs,
                "entities": ents, "centroid": _centroid([concepts[ci]["centroid"] for ci in cidxs]),
                "salience": float(sum(concepts[ci]["salience"] for ci in cidxs)),
                "document_ids": sorted({d for ci in cidxs for d in concepts[ci]["document_ids"]}),
                "_gal": concepts[cidxs[0]]["_gal"],
            }
        )
        con_label_to_idx[clabel] = len(constellations) - 1
        for ci in cidxs:
            concepts[ci]["parent_idx"] = len(constellations) - 1

    # Merge tiny outlier galaxies (a stray entity or two that maxclust split off -- e.g.
    # one medical term -> "Hematology") into their nearest real domain by centroid, so the
    # top level shows actual domains. A galaxy is "real" if it holds >= min_galaxy_concepts.
    min_gc = cfg["min_galaxy_concepts"]
    gl_concepts: dict[int, int] = defaultdict(int)
    for con in constellations:
        gl_concepts[con["_gal"]] += len(con["concept_idxs"])
    gl_centroid = {
        gl: _centroid([c["centroid"] for c in constellations if c["_gal"] == gl])
        for gl in gl_concepts
    }
    big = [gl for gl, n in gl_concepts.items() if n >= min_gc] or list(gl_concepts)
    for con in constellations:
        if con["_gal"] not in big:
            con["_gal"] = max(big, key=lambda b: _cos(gl_centroid[con["_gal"]], gl_centroid[b]))

    # level 0: galaxies (group constellations by galaxy label)
    gal_groups: dict[int, list[int]] = defaultdict(list)
    for coni, con in enumerate(constellations):
        gal_groups[con["_gal"]].append(coni)
    galaxies: list[dict] = []
    for _glabel, conidxs in gal_groups.items():
        gal_entities = sorted({e for coni in conidxs for e in constellations[coni]["entities"]})
        galaxies.append(
            {
                "level": LEVEL_GALAXY, "label": "", "constellation_idxs": conidxs,
                "entities": gal_entities,
                "centroid": _centroid([constellations[coni]["centroid"] for coni in conidxs]),
                "salience": float(sum(constellations[coni]["salience"] for coni in conidxs)),
                "document_ids": sorted(
                    {d for coni in conidxs for d in constellations[coni]["document_ids"]}
                ),
            }
        )
        for coni in conidxs:
            constellations[coni]["parent_idx"] = len(galaxies) - 1

    # Edges follow semantic distance (docs/concept-model-design.md §0) but are SPARSIFIED
    # to a k-NN graph: each concept links to its top-K nearest neighbours above the cutoff
    # (close ones strong, related-distant thin, unrelated none). All-pairs-above-cutoff
    # exploded to ~75k edges on bge-small (everything is somewhat similar) -- a hairball,
    # and brutal to persist. galaxy<->galaxy stays all-pairs (only ~8 galaxies).
    lateral = _knn_edges(
        [c["centroid"] for c in concepts],
        cfg["concept_edge_cutoff"], cfg["concept_edge_top_k"],
    )
    galaxy_edges = _knn_edges(
        [g["centroid"] for g in galaxies], cfg["galaxy_edge_cutoff"], len(galaxies),
    )

    state["hierarchy"] = {
        "galaxies": galaxies, "constellations": constellations, "concepts": concepts
    }
    state["lateral_edges"] = lateral
    state["galaxy_edges"] = galaxy_edges

    record(
        state,
        "build_hierarchy",
        {
            "galaxies": len(galaxies),
            "constellations": len(constellations),
            "concepts": len(concepts),
            "lateral_edges": len(lateral),
            "galaxy_edges": len(galaxy_edges),
            "galaxy_sample": [
                {
                    "n_constellations": len(g["constellation_idxs"]),
                    "n_docs": len(g["document_ids"]),
                    "top_entities": g["entities"][:10],
                }
                for g in sorted(galaxies, key=lambda x: -x["salience"])[:6]
            ],
            "concept_sample": [
                {"sun": c["sun"], "members": c["entities"][:8]}
                for c in sorted(concepts, key=lambda x: -x["salience"])[:20]
            ],
        },
    )
    return state
