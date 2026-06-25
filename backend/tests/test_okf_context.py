"""okf_context (GraphRAG grounding, docs/knowledge-model.md §9): resolve scope -> concepts ->
expand graph + evidence -> OKF text, and the self-contained POST /qa/grounded answer over it.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, ConceptModel
from app.services.okf_context import get_okf_context_service


class _FakeGraph:
    def __init__(self, nbrs=None):
        self._n = nbrs or {}

    def get_concept_neighbors(self, cid, limit=5):
        return self._n.get(cid, [])


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
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    graph_module._graph_service = orig_graph


async def _seed(factory):
    async with factory() as s:
        s.add(
            ConceptModel(
                id="c1", slug="c-1", label="Partitioning", kind="concept", status="proposed",
                level=2,
                evidence_json=[{"chunk_ids": ["ch1"], "document_ids": ["d1"], "members": ["p"]}],
            )
        )
        s.add(
            ConceptModel(
                id="c2", slug="c-2", label="Replication", kind="concept", status="proposed", level=2
            )
        )
        s.add(
            ChunkModel(
                id="ch1", document_id="d1",
                text="Partitioning splits data across nodes for scale.", chunk_index=0,
            )
        )
        await s.commit()


async def test_build_context_includes_evidence_and_related(test_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.okf_context.get_graph_service", lambda: _FakeGraph({"c1": ["c2"]})
    )
    await _seed(test_db)
    async with test_db() as s:
        ctx = await get_okf_context_service().build_concept_context(s, ["c1"])
    assert "## Partitioning" in ctx
    assert "splits data across nodes" in ctx
    assert "related: Replication" in ctx


async def test_resolve_query_lexical(test_db):
    await _seed(test_db)
    async with test_db() as s:
        ids = await get_okf_context_service().resolve_concepts(
            s, query="how does partitioning work"
        )
    assert ids == ["c1"]


async def test_grounded_endpoint_grounds_and_degrades(test_db, monkeypatch):
    monkeypatch.setattr("app.services.okf_context.get_graph_service", lambda: _FakeGraph({}))

    async def _complete(messages, **k):
        assert "Grounding context" in messages[1]["content"]  # the OKF block reaches the model
        return "Partitioning splits data. [answered]"

    monkeypatch.setattr(
        "app.routers.qa.get_llm_service",
        lambda: type("L", (), {"complete": staticmethod(_complete)})(),
    )
    await _seed(test_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/qa/grounded", json={"question": "how does partitioning work"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["grounded"] is True
        assert any(c["label"] == "Partitioning" for c in body["concepts"])
        assert "answered" in body["answer"]

        # nothing in the library matches -> honest, ungrounded
        r2 = await client.post("/qa/grounded", json={"question": "quantum chromodynamics symmetry"})
        assert r2.json()["grounded"] is False
