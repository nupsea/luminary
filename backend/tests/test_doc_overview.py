"""GET /documents/{id}/overview + POST /documents/{id}/collections (Phase 2).

The Doc overview aggregates header + collection memberships + tags; assignment adds a doc to
collections idempotently. (Study topics live in the Study tab, not this aggregate.)
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import CollectionModel
from tests.factories import make_document


@pytest.fixture
def test_db(memory_db):
    return memory_db.factory


async def _seed_doc(factory):
    async with factory() as s:
        s.add(
            make_document(
                id="d1",
                title="Iceberg Book",
                format="pdf",
                file_path="/tmp/x.pdf",
                tags=["data"],
                stage="parsing",
            )
        )
        s.add(CollectionModel(id="col1", name="DATA-ENG", color="#6366F1"))
        await s.commit()


async def test_overview_aggregates_header_and_collections(test_db):
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
    assert "concepts" not in body  # studyable list lives in the Study tab, not the overview
    assert [c["id"] for c in body["collections"]] == ["col1"]


async def test_overview_404_for_unknown_doc(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/documents/nope/overview")
    assert resp.status_code == 404
