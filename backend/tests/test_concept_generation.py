"""Concept generation: the multi-layer pipeline turns many entities into a small set of
higher-level themes (docs/concepts.md) and persists them with hierarchy. Mocks the
embedder / LLM / graph-reads; persistence + the Universe endpoint hit the real test DB.
"""

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.concept_extraction_service as ces
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ConceptModel

_DOCS = {
    "d1": {"t": ["Iceberg", "Parquet", "Partitioning", "Replication", "Consensus"]},
    "d2": {"t": ["Transformer", "Attention", "Embeddings", "Backprop"]},
    "d3": {"t": ["Dharma", "Karma", "Self Realization", "Gita"]},
}
_TOPIC = {
    **{k: 0 for k in _DOCS["d1"]["t"]},
    **{k: 1 for k in _DOCS["d2"]["t"]},
    **{k: 2 for k in _DOCS["d3"]["t"]},
}


def _fake_encode(names):
    out = []
    for n in names:
        v = np.zeros(384, dtype="float32")
        v[_TOPIC.get(n, 3)] = 1.0
        v += np.random.RandomState(abs(hash(n)) % 2**31).normal(0, 0.04, 384).astype("float32")
        out.append(v.tolist())
    return out


class _FakeGraph:
    def get_all_document_ids(self):
        return list(_DOCS)

    def get_entities_by_type_for_document(self, doc_id):
        return _DOCS[doc_id]

    # writes are no-ops in this test; reads used by the Universe endpoint return []
    def delete_all_concepts(self):
        pass

    def upsert_concept_node(self, *a, **k):
        pass

    def add_extracted_from(self, *a, **k):
        pass

    def add_concept_relation(self, *a, **k):
        pass


class _FakeLLM:
    async def complete(self, messages, temperature=0.0):
        terms = messages[-1]["content"].lower()
        if "iceberg" in terms or "replication" in terms:
            return "Data Systems"
        if "transformer" in terms or "attention" in terms:
            return "Machine Learning"
        if "dharma" in terms or "gita" in terms:
            return "Dharma"
        return "Theme"


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    orig_graph = graph_module._graph_service
    graph_module._graph_service = None

    # mock the pipeline's heavy deps
    _fake_embedder = type("E", (), {"encode": staticmethod(_fake_encode)})()
    monkeypatch.setattr(ces, "get_graph_service", lambda: _FakeGraph())
    monkeypatch.setattr(ces, "get_llm_service", lambda: _FakeLLM())
    monkeypatch.setattr(ces, "get_embedding_service", lambda: _fake_embedder)
    ces._extraction_service = None  # rebuild with the fake embedder

    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    graph_module._graph_service = orig_graph
    ces._extraction_service = None


async def test_regenerate_produces_themes_with_hierarchy(test_db):
    factory = test_db
    async with factory() as s:
        stats = await ces.regenerate(s, target_themes=3)
    assert stats["themes"] == 3

    async with factory() as s:
        themes = (
            await s.execute(select(ConceptModel).where(ConceptModel.level == 0))
        ).scalars().all()
        n_subs = await s.scalar(
            select(func.count()).select_from(ConceptModel).where(ConceptModel.level == 1)
        )
    assert sorted(t.label for t in themes) == ["Data Systems", "Dharma", "Machine Learning"]
    assert all(t.parent_id is None and t.salience > 0 for t in themes)
    assert n_subs >= 3  # at least one sub-concept per theme
    theme_ids = {t.id for t in themes}

    async with factory() as s:
        subs = (
            await s.execute(select(ConceptModel).where(ConceptModel.level == 1))
        ).scalars().all()
    assert all(sub.parent_id in theme_ids for sub in subs)


async def test_universe_shows_only_themes(test_db):
    factory = test_db
    async with factory() as s:
        await ces.regenerate(s, target_themes=3)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get("/concepts/universe")
    assert r.status_code == 200, r.text
    stars = r.json()["stars"]
    assert len(stars) == 3  # level-0 themes only, not the sub-concepts
    assert sorted(s["label"] for s in stars) == ["Data Systems", "Dharma", "Machine Learning"]
