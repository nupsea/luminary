"""build_hierarchy node -- the flat concept layer (docs/concept-model-design.md §0).

Verifies the dendrogram cut produces studyable concepts and that the distance-encoded
RELATED_TO edges never link unrelated domains (data-eng vs philosophy).
"""

import asyncio

import numpy as np

import app.workflows.concept_nodes.embed_entities as emb
import app.workflows.concept_nodes.select_entities as sel
from app.workflows.concept_pipeline import run_pipeline

# two clearly distinct domains (galaxies), two themes (constellations) each
_DOMAIN = {
    "iceberg": ("data", "storage"), "parquet": ("data", "storage"),
    "partitioning": ("data", "storage"), "replication": ("data", "reliab"),
    "consensus": ("data", "reliab"), "quorum": ("data", "reliab"),
    "dharma": ("phil", "spirit"), "karma": ("phil", "spirit"),
    "moksha": ("phil", "spirit"), "logic": ("phil", "reason"),
    "ethics": ("phil", "reason"), "epistemology": ("phil", "reason"),
}
_GAL = {"data": 0, "phil": 1}
_CON = {"storage": 0, "reliab": 1, "spirit": 2, "reason": 3}


def _encode(names):
    out = []
    for n in names:
        g, c = _DOMAIN[n]
        v = np.zeros(384, dtype="float32")
        v[0] = _GAL[g] * 3.0
        v[1 + _CON[c]] = 1.5
        v += np.random.RandomState(abs(hash(n)) % 2**31).normal(0, 0.01, 384).astype("float32")
        out.append(v.tolist())
    return out


class _FakeGraph:
    def get_all_document_ids(self):
        return ["d1", "d2"]

    def get_entities_detailed_for_document(self, doc_id):
        dom = "data" if doc_id == "d1" else "phil"
        return [
            {"name": n, "type": "CONCEPT", "frequency": 5}
            for n, (g, _c) in _DOMAIN.items()
            if g == dom
        ]


async def _run(monkeypatch):
    monkeypatch.setattr(sel, "get_graph_service", lambda: _FakeGraph())
    monkeypatch.setattr(
        emb, "get_embedding_service",
        lambda: type("E", (), {"encode": staticmethod(_encode)})(),
    )
    return await run_pipeline(dry_run=True)


def test_flat_concepts_with_no_cross_domain_edges(monkeypatch):
    state = asyncio.run(_run(monkeypatch))
    h = state["hierarchy"]
    # flat: a concept layer only -- no galaxy/constellation tiers
    assert h["concepts"]
    assert "galaxies" not in h and "constellations" not in h
    for c in h["concepts"]:
        assert c["level"] == 2 and c["label"] == c["sun"]
        assert "parent_idx" not in c

    # edges follow SEMANTIC DISTANCE, not a categorical wall: related concepts may link,
    # but UNRELATED domains (data-eng vs philosophy) must not.
    def domain_of(ci):
        ents = set(h["concepts"][ci]["entities"])
        if ents & set(_DOMAIN) and any(_DOMAIN[e][0] == "data" for e in ents if e in _DOMAIN):
            return "data"
        return "phil"

    bad = [
        (a, b) for a, b, _w in state["lateral_edges"]
        if domain_of(a) != domain_of(b)
    ]
    assert not bad, f"unrelated-domain edges leaked (data<->philosophy): {bad}"


def _concept(centroid, entities, salience, con, gal, sun):
    return {
        "level": 2, "label": "", "sun": sun, "entities": entities, "centroid": centroid,
        "salience": float(salience), "document_ids": ["d"], "_con": con, "_gal": gal,
    }


def test_dedup_merges_near_identical_keeps_distinct():
    from app.workflows.concept_nodes.build_hierarchy import _dedup_concepts

    base = [1.0, 0.0, 0.0, 0.0]
    near = [0.99, 0.02, 0.0, 0.0]   # cosine ~1.0 with base -> merge
    far = [0.0, 0.0, 1.0, 0.0]      # orthogonal -> stays distinct
    concepts = [
        _concept(base, ["a"], 10, 0, 0, "a"),
        _concept(near, ["b"], 3, 1, 0, "b"),
        _concept(far, ["z"], 5, 2, 1, "z"),
    ]
    merged, n = _dedup_concepts(concepts, 0.93)

    assert n == 1 and len(merged) == 2
    big = next(m for m in merged if "a" in m["entities"])
    assert sorted(big["entities"]) == ["a", "b"]   # folded
    assert big["sun"] == "a" and big["_con"] == 0  # most-salient member keeps identity
    assert big["salience"] == 13.0                 # salience summed
    assert any(m["entities"] == ["z"] for m in merged)  # distinct concept untouched


def test_dedup_is_conservative_below_cutoff():
    from app.workflows.concept_nodes.build_hierarchy import _dedup_concepts

    concepts = [
        _concept([1.0, 0.0, 0.0], ["a"], 1, 0, 0, "a"),
        _concept([0.7, 0.7, 0.0], ["b"], 1, 1, 0, "b"),  # cosine ~0.7 < 0.93
    ]
    merged, n = _dedup_concepts(concepts, 0.93)
    assert n == 0 and len(merged) == 2
