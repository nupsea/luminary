"""GET /documents/{id}/overview + POST /documents/{id}/collections (Phase 2).

The Doc overview aggregates header + extracted concepts (with evidence) + collection
memberships; assignment adds a doc to collections idempotently.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import CollectionModel, DocumentModel
from app.services.concept_service import get_concept_service


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


async def _seed_doc(factory):
    async with factory() as s:
        s.add(DocumentModel(id="d1", title="Iceberg Book", format="pdf",
                            content_type="book", file_path="/tmp/x.pdf", tags=["data"]))
        s.add(CollectionModel(id="col1", name="DATA-ENG", color="#6366F1"))
        await s.commit()
    graph_module._graph_service = None
    g = graph_module.get_graph_service()
    g.upsert_document("d1", "Iceberg Book", "book")
    svc = get_concept_service()
    async with factory() as s:
        await svc.create_concept(
            s, label="Manifests", origin="document", status="proposed",
            evidence=[{"document_id": "d1", "chunk_id": "c1", "quote": "a manifest list"}],
            document_ids=["d1"],
        )
        await s.commit()


async def test_overview_aggregates_concepts_and_collections(test_db):
    factory = test_db
    await _seed_doc(factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # assign the doc to a collection (P2b); returns the doc's collection set
        assign = await client.post("/documents/d1/collections", json={"collection_ids": ["col1"]})
        assert assign.status_code == 201, assign.text
        assert [c["id"] for c in assign.json()] == ["col1"]
        # idempotent: re-assign still shows exactly one membership (no duplicates)
        again = await client.post("/documents/d1/collections", json={"collection_ids": ["col1"]})
        assert [c["id"] for c in again.json()] == ["col1"]

        resp = await client.get("/documents/d1/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Iceberg Book" and body["tags"] == ["data"]
    assert [c["label"] for c in body["concepts"]] == ["Manifests"]
    assert body["concepts"][0]["evidence"][0]["quote"] == "a manifest list"
    assert [c["id"] for c in body["collections"]] == ["col1"]


async def test_overview_404_for_unknown_doc(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/documents/nope/overview")
    assert resp.status_code == 404
