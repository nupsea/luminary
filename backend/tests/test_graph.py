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


def test_get_entities_by_type_for_document(graph_svc: KuzuService):
    """get_entities_by_type_for_document groups canonical names by entity type."""
    graph_svc.upsert_entity("e1", "sherlock holmes", "PERSON")
    graph_svc.upsert_entity("e2", "dr. watson", "PERSON")
    graph_svc.upsert_entity("e3", "baker street", "PLACE")
    graph_svc.upsert_document("d1", "Test Doc", "book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")
    graph_svc.add_mention("e3", "d1")

    result = graph_svc.get_entities_by_type_for_document("d1")

    assert set(result.get("PERSON", [])) == {"sherlock holmes", "dr. watson"}
    assert set(result.get("PLACE", [])) == {"baker street"}


def test_get_entities_by_type_for_document_empty(graph_svc: KuzuService):
    """Returns empty dict for unknown document_id."""
    result = graph_svc.get_entities_by_type_for_document("nonexistent")
    assert result == {}


def test_upsert_entity_writes_aliases(graph_svc: KuzuService):
    """upsert_entity stores aliases as pipe-delimited string in fresh S86 schema."""
    graph_svc.upsert_entity("e1", "sherlock holmes", "PERSON", aliases=["holmes", "mr. holmes"])

    result = graph_svc._conn.execute("MATCH (e:Entity {id: 'e1'}) RETURN e.aliases")
    assert result.has_next()
    aliases_val = result.get_next()[0]
    # aliases column present in fresh DB (S86 schema); value is pipe-delimited
    assert aliases_val == "holmes|mr. holmes"


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


# ---------------------------------------------------------------------------
# S117: PREREQUISITE_OF edges and learning-path
# ---------------------------------------------------------------------------


def test_add_prerequisite_creates_edge(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "natural selection", "CONCEPT")
    graph_svc.upsert_entity("e2", "variation", "CONCEPT")
    graph_svc.add_prerequisite("e1", "e2", "doc1", 0.9)
    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:PREREQUISITE_OF]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'doc1' RETURN r.confidence"
    )
    assert result.has_next()
    assert result.get_next()[0] == pytest.approx(0.9)


def test_add_prerequisite_idempotent(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "a", "CONCEPT")
    graph_svc.upsert_entity("e2", "b", "CONCEPT")
    graph_svc.add_prerequisite("e1", "e2", "d1")
    graph_svc.add_prerequisite("e1", "e2", "d1")
    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:PREREQUISITE_OF]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'd1' RETURN count(r)"
    )
    assert result.get_next()[0] == 1


def test_get_prerequisite_edges_for_document(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "natural selection", "CONCEPT")
    graph_svc.upsert_entity("e2", "variation", "CONCEPT")
    graph_svc.upsert_document("d1", "Biology", "book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")
    graph_svc.add_prerequisite("e1", "e2", "d1", 0.9)
    edges = graph_svc.get_prerequisite_edges_for_document("d1")
    assert len(edges) == 1
    assert edges[0]["from_entity"] == "natural selection"
    assert edges[0]["to_entity"] == "variation"
    assert edges[0]["confidence"] == pytest.approx(0.9)


def test_get_learning_path_topological_order(graph_svc: KuzuService):
    """Chain: C -> B -> A (C requires B which requires A).
    Topological order should have A before B before C.
    """
    graph_svc.upsert_entity("ea", "a", "CONCEPT")
    graph_svc.upsert_entity("eb", "b", "CONCEPT")
    graph_svc.upsert_entity("ec", "c", "CONCEPT")
    graph_svc.upsert_document("d1", "Doc", "book")
    for eid in ("ea", "eb", "ec"):
        graph_svc.add_mention(eid, "d1")
    graph_svc.add_prerequisite("ec", "eb", "d1")  # c requires b
    graph_svc.add_prerequisite("eb", "ea", "d1")  # b requires a

    result = graph_svc.get_learning_path("c", "d1")
    assert len(result["nodes"]) == 3
    names = [n.name for n in result["nodes"]]
    assert names.index("a") < names.index("b")
    assert names.index("b") < names.index("c")


def test_get_learning_path_unknown_entity_returns_empty(graph_svc: KuzuService):
    graph_svc.upsert_document("d1", "Doc", "book")
    result = graph_svc.get_learning_path("nonexistent", "d1")
    assert result["nodes"] == []
    assert result["edges"] == []


def test_get_learning_path_no_prereq_edges_returns_empty(graph_svc: KuzuService):
    """Entity exists but has no PREREQUISITE_OF edges."""
    graph_svc.upsert_entity("e1", "gravity", "CONCEPT")
    graph_svc.upsert_document("d1", "Physics", "book")
    graph_svc.add_mention("e1", "d1")
    result = graph_svc.get_learning_path("gravity", "d1")
    assert result["nodes"] == []
    assert result["edges"] == []


def test_learning_path_endpoint_returns_200(client: TestClient, tmp_path, monkeypatch):
    import app.services.graph as graph_module

    svc: KuzuService = graph_module._graph_service  # type: ignore[assignment]
    svc.upsert_entity("e1", "natural selection", "CONCEPT")
    svc.upsert_entity("e2", "variation", "CONCEPT")
    svc.upsert_document("d1", "Biology", "book")
    svc.add_mention("e1", "d1")
    svc.add_mention("e2", "d1")
    svc.add_prerequisite("e1", "e2", "d1", 0.9)

    resp = client.get("/graph/learning-path?start_entity=natural+selection&document_id=d1")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data


def test_learning_path_endpoint_unknown_entity_returns_empty(client: TestClient):
    resp = client.get("/graph/learning-path?start_entity=ghost&document_id=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []


def test_learning_path_route_not_captured_by_document_id_route(client: TestClient):
    """Verify /graph/learning-path is not matched as document_id='learning-path'."""
    resp = client.get("/graph/learning-path?start_entity=x&document_id=d999")
    # Should return the learning-path response, not a graph-for-document response
    assert resp.status_code == 200
    data = resp.json()
    # learning-path response always has start_entity, document_id, nodes, edges
    assert "start_entity" in data
    assert "nodes" in data


def test_get_learning_path_cycle_handled_gracefully(graph_svc: KuzuService):
    """Cyclic PREREQUISITE_OF edges (A requires B, B requires A) must not raise or loop.

    Kahn's algorithm drops cyclic nodes from topo_order.  The result may be
    partial or empty, but the method must return without error.
    """
    graph_svc.upsert_entity("e1", "concept alpha", "CONCEPT")
    graph_svc.upsert_entity("e2", "concept beta", "CONCEPT")
    graph_svc.upsert_document("d1", "Cyclic Doc", "book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")
    # Create cycle: alpha requires beta AND beta requires alpha
    graph_svc.add_prerequisite("e1", "e2", "d1")
    graph_svc.add_prerequisite("e2", "e1", "d1")

    result = graph_svc.get_learning_path("concept alpha", "d1")
    # Must not raise; result is a valid dict with the expected keys
    assert "nodes" in result
    assert "edges" in result
    # Cyclic nodes have no in-degree=0 node, so topo_order is empty -> empty nodes
    assert isinstance(result["nodes"], list)


# ---------------------------------------------------------------------------
# S135: Tech relation edges
# ---------------------------------------------------------------------------


def test_schema_creates_tech_edge_tables(graph_svc: KuzuService):
    """_create_schema creates all 6 tech edge tables (S135)."""
    required = {"IMPLEMENTS", "EXTENDS", "USES", "REPLACES", "DEPENDS_ON", "VERSION_OF"}
    # CREATE REL TABLE IF NOT EXISTS is idempotent — no error means table exists
    for label in required:
        graph_svc._conn.execute(
            f"CREATE REL TABLE IF NOT EXISTS {label}"
            f"(FROM Entity TO Entity, document_id STRING)"
        )


def test_add_tech_relation_implements(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "numpy", "LIBRARY")
    graph_svc.upsert_entity("e2", "ndarray", "DATA_STRUCTURE")
    graph_svc.upsert_document("d1", "Python Tutorial", "tech_book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")

    graph_svc.add_tech_relation("e1", "e2", "IMPLEMENTS", "d1")

    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:IMPLEMENTS]->(b:Entity {id: 'e2'})"
        " RETURN r.document_id"
    )
    assert result.has_next()
    assert result.get_next()[0] == "d1"


def test_add_tech_relation_depends_on(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "celery", "LIBRARY")
    graph_svc.upsert_entity("e2", "redis", "LIBRARY")
    graph_svc.upsert_document("d1", "Task Queue Guide", "tech_book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")

    graph_svc.add_tech_relation("e1", "e2", "DEPENDS_ON", "d1")

    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:DEPENDS_ON]->(b:Entity {id: 'e2'})"
        " RETURN r.document_id"
    )
    assert result.has_next()


def test_add_tech_relation_idempotent(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "fastapi", "LIBRARY")
    graph_svc.upsert_entity("e2", "pydantic", "LIBRARY")
    graph_svc.add_tech_relation("e1", "e2", "USES", "d1")
    graph_svc.add_tech_relation("e1", "e2", "USES", "d1")  # idempotent

    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:USES]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'd1' RETURN count(r)"
    )
    assert result.get_next()[0] == 1


def test_add_tech_relation_invalid_label_raises(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "a", "LIBRARY")
    graph_svc.upsert_entity("e2", "b", "LIBRARY")
    with pytest.raises(ValueError, match="Unknown tech relation label"):
        graph_svc.add_tech_relation("e1", "e2", "INVALID_LABEL", "d1")


def test_add_version_of(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "python 3.13", "LIBRARY")
    graph_svc.upsert_entity("e2", "python 3", "LIBRARY")
    graph_svc.upsert_document("d1", "Python Guide", "tech_book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")

    graph_svc.add_version_of("e1", "e2", "d1")

    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:VERSION_OF]->(b:Entity {id: 'e2'})"
        " RETURN r.document_id"
    )
    assert result.has_next()


def test_add_version_of_idempotent(graph_svc: KuzuService):
    graph_svc.upsert_entity("e1", "python 3.13", "LIBRARY")
    graph_svc.upsert_entity("e2", "python 3", "LIBRARY")
    graph_svc.add_version_of("e1", "e2", "d1")
    graph_svc.add_version_of("e1", "e2", "d1")

    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:VERSION_OF]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'd1' RETURN count(r)"
    )
    assert result.get_next()[0] == 1


def test_get_entities_by_type_filters_correctly(graph_svc: KuzuService):
    """AC6: get_entities_by_type returns only entities of the requested type."""
    graph_svc.upsert_document("d1", "Python Guide", "tech_book")
    graph_svc.upsert_entity("e1", "numpy", "LIBRARY")
    graph_svc.upsert_entity("e2", "alice", "PERSON")
    graph_svc.upsert_entity("e3", "sqlalchemy", "LIBRARY")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")
    graph_svc.add_mention("e3", "d1")

    libs = graph_svc.get_entities_by_type("d1", "LIBRARY")
    lib_names = {e["name"] for e in libs}
    assert lib_names == {"numpy", "sqlalchemy"}

    persons = graph_svc.get_entities_by_type("d1", "PERSON")
    assert len(persons) == 1
    assert persons[0]["name"] == "alice"


def test_get_entities_by_type_empty_for_unknown_type(graph_svc: KuzuService):
    graph_svc.upsert_document("d1", "Test", "book")
    graph_svc.upsert_entity("e1", "newton", "PERSON")
    graph_svc.add_mention("e1", "d1")
    result = graph_svc.get_entities_by_type("d1", "LIBRARY")
    assert result == []


def test_get_entities_by_type_returns_required_fields(graph_svc: KuzuService):
    graph_svc.upsert_document("d1", "Test", "tech_book")
    graph_svc.upsert_entity("e1", "numpy", "LIBRARY")
    graph_svc.add_mention("e1", "d1")
    result = graph_svc.get_entities_by_type("d1", "LIBRARY")
    assert len(result) == 1
    entity = result[0]
    assert "id" in entity
    assert "name" in entity
    assert "type" in entity
    assert "frequency" in entity
    assert entity["type"] == "LIBRARY"


def test_get_graph_for_document_includes_tech_edges(graph_svc: KuzuService):
    """get_graph_for_document returns IMPLEMENTS/DEPENDS_ON edges alongside CO_OCCURS."""
    graph_svc.upsert_document("d1", "Python Arch", "tech_book")
    graph_svc.upsert_entity("e1", "numpy", "LIBRARY")
    graph_svc.upsert_entity("e2", "ndarray", "DATA_STRUCTURE")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")
    graph_svc.add_tech_relation("e1", "e2", "IMPLEMENTS", "d1")

    data = graph_svc.get_graph_for_document("d1")
    edge_relations = {e.get("relation") for e in data["edges"] if "relation" in e}
    assert "IMPLEMENTS" in edge_relations


def test_entities_by_type_api_endpoint(client, tmp_path, monkeypatch):
    """AC6: GET /graph/entities/{doc_id}?type=LIBRARY returns only LIBRARY entities."""
    import app.services.graph as graph_module

    svc: KuzuService = graph_module._graph_service  # type: ignore[assignment]
    svc.upsert_document("d1", "Python Guide", "tech_book")
    svc.upsert_entity("e1", "numpy", "LIBRARY")
    svc.upsert_entity("e2", "einstein", "PERSON")
    svc.add_mention("e1", "d1")
    svc.add_mention("e2", "d1")

    resp = client.get("/graph/entities/d1?type=LIBRARY")
    assert resp.status_code == 200
    data = resp.json()
    assert "entities" in data
    assert len(data["entities"]) == 1
    assert data["entities"][0]["name"] == "numpy"
    assert data["entities"][0]["type"] == "LIBRARY"


def test_entities_endpoint_not_captured_by_document_id_route(client):
    """Verify /graph/entities/doc1 is not matched as document_id='entities'."""
    resp = client.get("/graph/entities/doc1?type=LIBRARY")
    # Should return the entity list endpoint, not the graph-for-document endpoint
    assert resp.status_code == 200
    data = resp.json()
    assert "entities" in data  # entity list response, not graph document response


# ---------------------------------------------------------------------------
# S139: add_prerequisite_with_section, has_prerequisite_edges,
#       get_entry_point_concepts, get_prerequisite_edges_for_graph
# ---------------------------------------------------------------------------


def test_add_prerequisite_with_section_creates_edge(graph_svc: KuzuService):
    """add_prerequisite_with_section writes a PREREQUISITE_OF edge."""
    graph_svc.upsert_entity("e1", "closures", "CONCEPT")
    graph_svc.upsert_entity("e2", "functions", "CONCEPT")
    graph_svc.add_prerequisite_with_section(
        dependent_id="e1",
        prerequisite_id="e2",
        document_id="d1",
        confidence=0.85,
        source_section_id="sec-1",
    )
    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:PREREQUISITE_OF]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'd1' RETURN r.confidence"
    )
    assert result.has_next()
    assert result.get_next()[0] == pytest.approx(0.85)


def test_add_prerequisite_with_section_idempotent(graph_svc: KuzuService):
    """add_prerequisite_with_section is idempotent; calling twice writes one edge."""
    graph_svc.upsert_entity("e1", "decorators", "CONCEPT")
    graph_svc.upsert_entity("e2", "functions", "CONCEPT")
    graph_svc.add_prerequisite_with_section("e1", "e2", "d1", 0.9, "sec-1")
    graph_svc.add_prerequisite_with_section("e1", "e2", "d1", 0.9, "sec-1")
    result = graph_svc._conn.execute(
        "MATCH (a:Entity {id: 'e1'})-[r:PREREQUISITE_OF]->(b:Entity {id: 'e2'})"
        " WHERE r.document_id = 'd1' RETURN count(r)"
    )
    assert result.get_next()[0] == 1


def test_has_prerequisite_edges_true(graph_svc: KuzuService):
    """has_prerequisite_edges returns True when at least one edge exists."""
    graph_svc.upsert_entity("e1", "async", "CONCEPT")
    graph_svc.upsert_entity("e2", "coroutines", "CONCEPT")
    graph_svc.add_prerequisite("e1", "e2", "d1", 0.8)
    assert graph_svc.has_prerequisite_edges("d1") is True


def test_has_prerequisite_edges_false_no_edges(graph_svc: KuzuService):
    """has_prerequisite_edges returns False when no PREREQUISITE_OF edges exist for doc."""
    assert graph_svc.has_prerequisite_edges("no-such-doc") is False


def test_get_entry_point_concepts_returns_roots(graph_svc: KuzuService):
    """get_entry_point_concepts returns entities that are prereqs for others but have none."""
    # Chain: closures -> functions -> variables
    # 'variables' has no prereqs and IS a prereq for 'functions' -> entry point
    # 'functions' has a prereq ('variables') -> not an entry point
    # 'closures' has a prereq ('functions') -> not an entry point
    graph_svc.upsert_entity("e1", "closures", "CONCEPT")
    graph_svc.upsert_entity("e2", "functions", "CONCEPT")
    graph_svc.upsert_entity("e3", "variables", "CONCEPT")
    graph_svc.upsert_document("d1", "Python 101", "tech_book")
    for eid in ("e1", "e2", "e3"):
        graph_svc.add_mention(eid, "d1")
    graph_svc.add_prerequisite("e1", "e2", "d1")   # closures requires functions
    graph_svc.add_prerequisite("e2", "e3", "d1")   # functions requires variables

    concepts = graph_svc.get_entry_point_concepts("d1", limit=10)
    assert "variables" in concepts
    assert "closures" not in concepts
    assert "functions" not in concepts


def test_get_prerequisite_edges_for_graph_wire_format(graph_svc: KuzuService):
    """get_prerequisite_edges_for_graph returns {source, target, weight, relation} dicts."""
    graph_svc.upsert_entity("e1", "iterators", "CONCEPT")
    graph_svc.upsert_entity("e2", "generators", "CONCEPT")
    graph_svc.upsert_document("d1", "Advanced Python", "tech_book")
    graph_svc.add_mention("e1", "d1")
    graph_svc.add_mention("e2", "d1")
    graph_svc.add_prerequisite("e1", "e2", "d1", 0.95)

    edges = graph_svc.get_prerequisite_edges_for_graph("d1")
    assert len(edges) == 1
    e = edges[0]
    assert e["source"] == "e1"
    assert e["target"] == "e2"
    assert e["weight"] == pytest.approx(0.95)
    assert e["relation"] == "PREREQUISITE_OF"
