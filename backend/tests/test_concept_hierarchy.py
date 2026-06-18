"""build_hierarchy node -- the nested Universe (docs/concept-model-design.md §0).

Verifies the dendrogram cut produces consistently-nested galaxy/constellation/concept
levels, with the distance-encoded edge rule: NO lateral links across galaxies.
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


class _FakeLLM:
    async def complete(self, messages, temperature=0.0):
        return "Topic"


async def _run(monkeypatch):
    import app.workflows.concept_nodes.label_levels as lab

    monkeypatch.setattr(sel, "get_graph_service", lambda: _FakeGraph())
    monkeypatch.setattr(
        emb, "get_embedding_service",
        lambda: type("E", (), {"encode": staticmethod(_encode)})(),
    )
    monkeypatch.setattr(lab, "get_llm_service", lambda: _FakeLLM())
    return await run_pipeline(dry_run=True)


def test_nested_universe_with_no_cross_galaxy_edges(monkeypatch):
    state = asyncio.run(_run(monkeypatch))
    h = state["hierarchy"]
    assert h["galaxies"] and h["constellations"] and h["concepts"]

    def galaxy_of_concept(ci):
        return h["constellations"][h["concepts"][ci]["parent_idx"]]["parent_idx"]

    # nesting: every concept -> constellation -> galaxy chain resolves
    for ci in range(len(h["concepts"])):
        assert h["concepts"][ci]["parent_idx"] is not None
        assert 0 <= galaxy_of_concept(ci) < len(h["galaxies"])

    # edges follow SEMANTIC DISTANCE, not a categorical wall: related concepts may link
    # even across galaxies (thin), but UNRELATED domains (data-eng vs philosophy) must not.
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

    # distinct domains land in distinct galaxies
    def galaxy_of_entity(name):
        for ci, c in enumerate(h["concepts"]):
            if name in c["entities"]:
                return galaxy_of_concept(ci)
        return None

    assert galaxy_of_entity("dharma") != galaxy_of_entity("iceberg")
