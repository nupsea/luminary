"""Tests for GET /chat/explorations and KuzuService.get_related_entity_pairs_for_document."""

import pytest
from fastapi.testclient import TestClient

import app.services.graph as graph_module
from app.main import app
from app.services.graph import KuzuService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph_svc(tmp_path):
    """Fresh KuzuService in a temp directory — isolated from production data."""
    return KuzuService(data_dir=str(tmp_path))


@pytest.fixture()
def client(tmp_path):
    """TestClient with the graph singleton patched to an isolated temp-dir instance.

    Follows the same pattern as test_graph.py (monkeypatch _graph_service) to
    prevent the API endpoint tests from writing test litter into the shared
    session-scoped Kuzu database.
    """
    svc = KuzuService(data_dir=str(tmp_path))
    orig = graph_module._graph_service
    graph_module._graph_service = svc
    try:
        with TestClient(app) as c:
            yield c
    finally:
        graph_module._graph_service = orig


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


def test_get_related_pairs_empty_for_no_entities(graph_svc: KuzuService):
    """Returns empty list when no RELATED_TO edges exist for the document."""
    pairs = graph_svc.get_related_entity_pairs_for_document("doc-missing", limit=5)
    assert pairs == []


def test_get_related_pairs_returns_pairs(graph_svc: KuzuService):
    """Returns entity pairs when RELATED_TO edges exist for the document."""
    graph_svc.upsert_entity("e1", "eloi", "CONCEPT")
    graph_svc.upsert_entity("e2", "morlocks", "CONCEPT")
    graph_svc.upsert_document("doc-tm", "The Time Machine", "book")
    graph_svc.add_mention("e1", "doc-tm")
    graph_svc.add_mention("e2", "doc-tm")
    graph_svc.add_relation("e1", "e2", "contrast", confidence=0.9)

    pairs = graph_svc.get_related_entity_pairs_for_document("doc-tm", limit=5)
    assert len(pairs) == 1
    name_a, name_b, label, conf = pairs[0]
    assert name_a == "eloi"
    assert name_b == "morlocks"
    assert label == "contrast"
    assert conf == pytest.approx(0.9, abs=0.01)


def test_get_related_pairs_ordered_by_confidence(graph_svc: KuzuService):
    """Pairs are returned in descending confidence order."""
    for i, name in enumerate(["alice", "rabbit", "queen"]):
        graph_svc.upsert_entity(f"e{i}", name, "PERSON")
        graph_svc.add_mention(f"e{i}", "doc-aw")
    graph_svc.upsert_document("doc-aw", "Alice in Wonderland", "book")
    graph_svc.add_mention("e0", "doc-aw")
    graph_svc.add_mention("e1", "doc-aw")
    graph_svc.add_mention("e2", "doc-aw")

    graph_svc.add_relation("e0", "e1", "follows", confidence=0.5)
    graph_svc.add_relation("e1", "e2", "opposes", confidence=0.95)

    pairs = graph_svc.get_related_entity_pairs_for_document("doc-aw", limit=5)
    assert len(pairs) == 2
    # Higher confidence first
    assert pairs[0][3] >= pairs[1][3]


def test_get_related_pairs_respects_limit(graph_svc: KuzuService):
    """Only up to *limit* pairs are returned."""
    graph_svc.upsert_document("doc-lim", "Limit Test", "book")
    for i in range(6):
        graph_svc.upsert_entity(f"e{i}", f"entity{i}", "CONCEPT")
        graph_svc.add_mention(f"e{i}", "doc-lim")
    for i in range(5):
        graph_svc.add_relation(f"e{i}", f"e{i+1}", "linked", confidence=float(i) / 5)

    pairs = graph_svc.get_related_entity_pairs_for_document("doc-lim", limit=3)
    assert len(pairs) <= 3


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def test_explorations_returns_200_empty_for_unknown_doc(client):
    """GET /chat/explorations with unknown doc returns HTTP 200 and empty list."""
    resp = client.get("/chat/explorations?document_id=nonexistent-doc-xyz")
    assert resp.status_code == 200
    assert resp.json() == []


def test_explorations_returns_suggestions_text_format(client):
    """ExplorationSuggestion.text is formatted correctly with and without relation_label."""
    # Use the singleton patched by the client fixture (isolated tmp_path instance).
    svc = graph_module._graph_service
    doc_id = "s109-test-doc"
    svc.upsert_entity("s109-e1", "time traveller", "PERSON")
    svc.upsert_entity("s109-e2", "weena", "PERSON")
    svc.upsert_document(doc_id, "Time Machine S109", "book")
    svc.add_mention("s109-e1", doc_id)
    svc.add_mention("s109-e2", doc_id)
    svc.add_relation("s109-e1", "s109-e2", "rescues", confidence=0.8)

    resp = client.get(f"/chat/explorations?document_id={doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    suggestion = data[0]
    assert "text" in suggestion
    assert "entity_names" in suggestion
    # relation_label "rescues" present -> "What is the rescues between ..."
    assert "rescues" in suggestion["text"] or "How is" in suggestion["text"]
    assert "time traveller" in suggestion["entity_names"] or "weena" in suggestion["entity_names"]
