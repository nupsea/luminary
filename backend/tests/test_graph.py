"""Tests for KuzuService and GET /graph endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.services.graph import KuzuService

# ---------------------------------------------------------------------------
# Unit tests for KuzuService (uses a temp directory)
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph_svc(tmp_path):
    """Create a fresh KuzuService in a temp directory."""
    return KuzuService(data_dir=str(tmp_path))


def test_upsert_entity_and_retrieve(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Albert Einstein", "PERSON")
    result = graph_svc._conn.execute("MATCH (e:Entity {id: 'e1'}) RETURN e.name, e.type")
    assert result.has_next()
    row = result.get_next()
    assert row[0] == "Albert Einstein"
    assert row[1] == "PERSON"


def test_upsert_entity_increments_frequency(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Tesla", "ORGANIZATION")
    graph_svc.upsert_entity("e1", "Tesla", "ORGANIZATION")
    result = graph_svc._conn.execute("MATCH (e:Entity {id: 'e1'}) RETURN e.frequency")
    row = result.get_next()
    assert row[0] == 2


def test_upsert_document(graph_svc: KuzuService):
    graph_svc.upsert_document("d1", "My Paper", "paper")
    result = graph_svc._conn.execute("MATCH (d:Document {id: 'd1'}) RETURN d.title")
    assert result.has_next()
    assert result.get_next()[0] == "My Paper"


def test_add_mention_creates_edge(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Newton", "PERSON")
    graph_svc.upsert_document("d1", "Physics Book", "book")
    graph_svc.add_mention("e1", "d1")
    result = graph_svc._conn.execute(
        "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: 'd1'}) RETURN r.count"
    )
    assert result.has_next()
    assert result.get_next()[0] == 1


def test_add_mention_increments_count(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Newton", "PERSON")
    graph_svc.upsert_document("d1", "Physics Book", "book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e1", "d1")
    result = graph_svc._conn.execute(
        "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: 'd1'}) RETURN r.count"
    )
    assert result.get_next()[0] == 2


def test_add_co_occurrence(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Newton", "PERSON")
    graph_svc.upsert_entity("e2", "Gravity", "CONCEPT")
    graph_svc.add_co_occurrence("e1", "e2", "d1")
    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:CO_OCCURS]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'd1' RETURN r.weight"
    )
    assert result.has_next()
    assert result.get_next()[0] == pytest.approx(1.0)


def test_get_graph_for_document(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Darwin", "PERSON")
    graph_svc.upsert_entity("e2", "Evolution", "CONCEPT")
    graph_svc.upsert_document("d1", "Origin of Species", "book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")

    data = graph_svc.get_graph_for_document("d1")
    node_ids = {n["id"] for n in data["nodes"]}
    assert "e1" in node_ids
    assert "e2" in node_ids
    assert len(data["nodes"]) == 2


def test_get_graph_for_documents_merges(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Darwin", "PERSON")
    graph_svc.upsert_entity("e2", "Evolution", "CONCEPT")
    graph_svc.upsert_document("d1", "Book One", "book")
    graph_svc.upsert_document("d2", "Book Two", "book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d2")

    data = graph_svc.get_graph_for_documents(["d1", "d2"])
    node_ids = {n["id"] for n in data["nodes"]}
    assert "e1" in node_ids
    assert "e2" in node_ids


def test_delete_document(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "Darwin", "PERSON")
    graph_svc.upsert_document("d1", "Origin", "book")
    graph_svc.add_mention("e1", "d1")

    graph_svc.delete_document("d1")

    result = graph_svc._conn.execute("MATCH (d:Document {id: 'd1'}) RETURN d.id")
    assert not result.has_next()

    # Edge should be gone too
    result = graph_svc._conn.execute(
        "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: 'd1'}) RETURN r.count"
    )
    assert not result.has_next()


def test_empty_graph_for_unknown_document(graph_svc: KuzuService):
    data = graph_svc.get_graph_for_document("nonexistent")
    assert data == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Integration tests via FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI test client with KuzuService pointing to temp dir."""
    import app.services.graph as graph_module
    from app.main import app as fastapi_app

    # Patch the singleton to use a temp-dir KuzuService
    svc = KuzuService(data_dir=str(tmp_path))
    monkeypatch.setattr(graph_module, "_graph_service", svc)

    return TestClient(fastapi_app)


def test_get_graph_document_endpoint(client: TestClient, tmp_path, monkeypatch):
    import app.services.graph as graph_module

    svc: KuzuService = graph_module._graph_service  # type: ignore[assignment]
    svc.upsert_entity("e1", "Curie", "PERSON")
    svc.upsert_document("d1", "Radioactivity", "paper")
    svc.add_mention("e1", "d1")

    resp = client.get("/graph/d1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["label"] == "Curie"


def test_get_graph_multi_doc_endpoint(client: TestClient, tmp_path, monkeypatch):
    import app.services.graph as graph_module

    svc: KuzuService = graph_module._graph_service  # type: ignore[assignment]
    svc.upsert_entity("e1", "Curie", "PERSON")
    svc.upsert_entity("e2", "Radium", "CONCEPT")
    svc.upsert_document("d1", "Paper One", "paper")
    svc.upsert_document("d2", "Paper Two", "paper")
    svc.add_mention("e1", "d1")
    svc.add_mention("e2", "d2")

    resp = client.get("/graph?doc_ids=d1,d2")
    assert resp.status_code == 200
    data = resp.json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "e1" in node_ids
    assert "e2" in node_ids


def test_get_graph_empty_doc_ids(client: TestClient):
    resp = client.get("/graph?doc_ids=")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
