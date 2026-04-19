"""Tests for S163: Notes as Kuzu graph nodes.

Uses a real in-memory Kuzu instance (tmp_path) so Cypher queries are verified
without mocking the graph layer. GLiNER is mocked to return controlled entity lists.
"""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.graph import KuzuService
from app.services.note_graph import NoteGraphService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kuzu_service(tmp_path):
    """Real KuzuService backed by a temp directory -- reset per test."""
    return KuzuService(str(tmp_path))


@pytest.fixture()
def note_graph_svc(kuzu_service):
    """NoteGraphService patched to use the test KuzuService instance."""
    svc = NoteGraphService()
    # Patch get_graph_service used inside note_graph.py methods
    with patch("app.services.note_graph.get_note_graph_service", return_value=svc):
        with patch("app.services.graph.get_graph_service", return_value=kuzu_service):
            yield svc, kuzu_service


def _seed_entity(ks: KuzuService, name: str, etype: str = "CONCEPT") -> str:
    """Insert an Entity node and return its id."""
    entity_id = str(uuid.uuid4())
    ks._conn.execute(
        "CREATE (:Entity {id: $id, name: $name, type: $type, frequency: 1, aliases: ''})",
        {"id": entity_id, "name": name, "type": etype},
    )
    return entity_id


def _seed_document(ks: KuzuService, doc_id: str | None = None) -> str:
    """Insert a Document node and return its id."""
    doc_id = doc_id or str(uuid.uuid4())
    ks._conn.execute(
        "CREATE (:Document {id: $id, title: 'Test Doc', content_type: 'book'})",
        {"id": doc_id},
    )
    return doc_id


def _mock_extractor(entity_name: str, score: float = 0.9):
    """Return a mock EntityExtractor that yields one entity."""
    mock = MagicMock()
    mock.extract.return_value = [
        {"name": entity_name, "type": "CONCEPT", "score": score, "chunk_id": "c1"}
    ]
    return mock


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test: upsert_note_node -- WRITTEN_ABOUT edge for known entity
# ---------------------------------------------------------------------------


def test_written_about_edge_created_for_known_entity(note_graph_svc, tmp_path):
    svc, ks = note_graph_svc
    entity_id = _seed_entity(ks, "gradient descent", "CONCEPT")
    note_id = str(uuid.uuid4())

    mock_ext = _mock_extractor("gradient descent")
    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=mock_ext),
    ):
        _run(svc.upsert_note_node(note_id, "Notes on gradient descent optimization.", None, []))

    result = ks._conn.execute(
        "MATCH (n:Note {id: $nid})-[r:WRITTEN_ABOUT]->(e:Entity {id: $eid}) RETURN r.confidence",
        {"nid": note_id, "eid": entity_id},
    )
    assert result.has_next(), "WRITTEN_ABOUT edge should exist"
    row = result.get_next()
    assert isinstance(row[0], float)


def test_absent_entity_skipped_without_exception(note_graph_svc):
    svc, ks = note_graph_svc
    # No Entity nodes seeded -- extractor returns a name that does not exist in Kuzu
    note_id = str(uuid.uuid4())

    mock_ext = _mock_extractor("nonexistent entity xyz")
    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=mock_ext),
    ):
        # Should not raise
        _run(
            svc.upsert_note_node(
                note_id, "Some content mentioning nonexistent entity xyz.", None, []
            )
        )

    # Note node should still have been created
    result = ks._conn.execute("MATCH (n:Note {id: $id}) RETURN n.id", {"id": note_id})
    assert result.has_next(), "Note node should be created even when entity is absent"


# ---------------------------------------------------------------------------
# Test: DERIVED_FROM edge when note has document_id and Document node exists
# ---------------------------------------------------------------------------


def test_derived_from_edge_created(note_graph_svc):
    svc, ks = note_graph_svc
    doc_id = _seed_document(ks)
    note_id = str(uuid.uuid4())

    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=_mock_extractor("")),
    ):
        _run(svc.upsert_note_node(note_id, "A note with a source doc.", doc_id, []))

    result = ks._conn.execute(
        "MATCH (n:Note {id: $nid})-[:DERIVED_FROM]->(d:Document {id: $did}) RETURN n.id",
        {"nid": note_id, "did": doc_id},
    )
    assert result.has_next(), "DERIVED_FROM edge should exist when Document node present"


def test_derived_from_edge_skipped_when_doc_absent(note_graph_svc):
    svc, ks = note_graph_svc
    note_id = str(uuid.uuid4())
    fake_doc_id = str(uuid.uuid4())  # Document NOT in Kuzu

    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=_mock_extractor("")),
    ):
        _run(svc.upsert_note_node(note_id, "Note without matching doc.", fake_doc_id, []))

    result = ks._conn.execute(
        "MATCH (n:Note {id: $id})-[:DERIVED_FROM]->() RETURN n.id", {"id": note_id}
    )
    assert not result.has_next(), "No DERIVED_FROM edge when Document node absent"


# ---------------------------------------------------------------------------
# Test: TAG_IS_CONCEPT edge when tag matches Entity.name (case-insensitive)
# ---------------------------------------------------------------------------


def test_tag_is_concept_edge_created(note_graph_svc):
    svc, ks = note_graph_svc
    entity_id = _seed_entity(ks, "Neural Networks", "CONCEPT")
    note_id = str(uuid.uuid4())

    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=_mock_extractor("")),
    ):
        _run(svc.upsert_note_node(note_id, "Content.", None, ["neural networks"]))

    result = ks._conn.execute(
        "MATCH (n:Note {id: $nid})-[r:TAG_IS_CONCEPT]->(e:Entity {id: $eid}) RETURN r.tag",
        {"nid": note_id, "eid": entity_id},
    )
    assert result.has_next(), "TAG_IS_CONCEPT edge should exist for matching tag"


# ---------------------------------------------------------------------------
# Test: delete_note_node removes Note; get_entities_for_note returns []
# ---------------------------------------------------------------------------


def test_delete_note_node_and_verify_entities_empty(note_graph_svc):
    svc, ks = note_graph_svc
    entity_id = _seed_entity(ks, "backpropagation")
    note_id = str(uuid.uuid4())

    mock_ext = _mock_extractor("backpropagation")
    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=mock_ext),
    ):
        _run(svc.upsert_note_node(note_id, "Backpropagation is key.", None, []))

    # Verify edge was created
    result = ks._conn.execute(
        "MATCH (n:Note {id: $nid})-[:WRITTEN_ABOUT]->(e:Entity {id: $eid}) RETURN n.id",
        {"nid": note_id, "eid": entity_id},
    )
    assert result.has_next(), "Edge should exist before delete"

    with patch("app.services.graph.get_graph_service", return_value=ks):
        _run(svc.delete_note_node(note_id))

    # Note node should be gone
    node_result = ks._conn.execute("MATCH (n:Note {id: $id}) RETURN n.id", {"id": note_id})
    assert not node_result.has_next(), "Note node should be deleted"

    # get_entities_for_note should return []
    with patch("app.services.graph.get_graph_service", return_value=ks):
        entities = _run(svc.get_entities_for_note(note_id))
    assert entities == [], "get_entities_for_note should return [] for deleted note"


# ---------------------------------------------------------------------------
# Test: get_notes_for_entity returns correct note_id
# ---------------------------------------------------------------------------


def test_get_notes_for_entity(note_graph_svc):
    svc, ks = note_graph_svc
    _seed_entity(ks, "Attention Mechanism", "CONCEPT")
    note_id = str(uuid.uuid4())

    mock_ext = _mock_extractor("Attention Mechanism", 0.95)
    with (
        patch("app.services.graph.get_graph_service", return_value=ks),
        patch("app.services.ner.get_entity_extractor", return_value=mock_ext),
    ):
        _run(svc.upsert_note_node(note_id, "Attention mechanism in transformers.", None, []))

    with patch("app.services.graph.get_graph_service", return_value=ks):
        note_ids = _run(svc.get_notes_for_entity("attention mechanism"))
    assert note_id in note_ids


# ---------------------------------------------------------------------------
# Test: GET /notes/{note_id}/entities endpoint returns correct shape
# ---------------------------------------------------------------------------


def test_get_note_entities_endpoint(tmp_path):
    """GET /notes/{note_id}/entities returns a JSON list with name/type/confidence/edge_type."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        # Create a note to get a valid note_id
        resp = client.post("/notes", json={"content": "Test entity endpoint note."})
        assert resp.status_code == 201
        note_id = resp.json()["id"]

        # Endpoint should return 200 with a list (possibly empty since GLiNER not running)
        resp = client.get(f"/notes/{note_id}/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Each item must have required fields if present
        for item in data:
            assert "name" in item
            assert "type" in item
            assert "confidence" in item
            assert "edge_type" in item
