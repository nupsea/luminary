"""Tests for notes FTS + semantic search (S91).

Test plan:
  1. test_sanitize_fts_query_strips_operators — pure unit test on _sanitize_fts_query
  2. test_rrf_merge_fts_only — pure unit: FTS results only, source=="fts"
  3. test_rrf_merge_vector_only — pure unit: vector results only, source=="vector"
  4. test_rrf_merge_dedup_both_source — pure unit: same note_id in both arms -> source=="both"
  5. test_fts_finds_exact_match — integration: insert note, search FTS, assert hit
  6. test_search_endpoint_200 — API: POST /notes then GET /notes/search?q=term
  7. test_search_endpoint_422_empty_q — API: GET /notes/search?q= returns 422
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.note_search import _rrf_merge, _sanitize_fts_query
from app.types import NoteSearchResult

pytest_plugins = ["conftest_books"]

# ---------------------------------------------------------------------------
# Unit tests (pure functions — no I/O)
# ---------------------------------------------------------------------------


def test_sanitize_fts_query_strips_operators():
    result = _sanitize_fts_query("What? AND how OR why NOT")
    assert "AND" not in result
    assert "OR" not in result
    assert "NOT" not in result
    assert "?" not in result
    words = result.split()
    assert "What" in words
    assert "how" in words
    assert "why" in words


def _make_result(note_id: str, content: str, score: float, source: str) -> NoteSearchResult:
    return NoteSearchResult(
        note_id=note_id,
        content=content,
        tags=[],
        group_name=None,
        document_id=None,
        score=score,
        source=source,  # type: ignore[arg-type]
    )


def test_rrf_merge_fts_only():
    fts = [
        _make_result("n1", "a", 1.0, "fts"),
        _make_result("n2", "b", 0.8, "fts"),
    ]
    merged = _rrf_merge(fts, [], k=10)
    assert len(merged) == 2
    assert all(r.source == "fts" for r in merged)
    note_ids = [r.note_id for r in merged]
    assert "n1" in note_ids
    assert "n2" in note_ids


def test_rrf_merge_vector_only():
    vector = [
        _make_result("v1", "x", 0.9, "vector"),
        _make_result("v2", "y", 0.7, "vector"),
    ]
    merged = _rrf_merge([], vector, k=10)
    assert len(merged) == 2
    assert all(r.source == "vector" for r in merged)


def test_rrf_merge_dedup_both_source():
    """Same note_id at rank 1 in both arms — should appear once with source='both'."""
    fts = [_make_result("shared", "c", 1.0, "fts")]
    vector = [_make_result("shared", "c", 0.95, "vector")]
    merged = _rrf_merge(fts, vector, k=10)
    assert len(merged) == 1
    assert merged[0].note_id == "shared"
    assert merged[0].source == "both"


# ---------------------------------------------------------------------------
# Integration + API tests (use TestClient(app) — lifespan creates in-memory DB)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_fts_finds_exact_match(client):
    """POST a note, then FTS search returns it."""
    content = "The White Rabbit led Alice into Wonderland"
    create = client.post("/notes", json={"content": content, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    resp = client.get("/notes/search", params={"q": "White Rabbit"})
    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["note_id"] for r in data["results"]]
    assert note_id in result_ids


def test_search_endpoint_200(client):
    """POST /notes then GET /notes/search returns 200 with results."""
    content = "Cheshire Cat can vanish leaving only its grin"
    create = client.post("/notes", json={"content": content, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    resp = client.get("/notes/search", params={"q": "Cheshire Cat", "semantic": "false"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert data["total"] >= 1
    result_ids = [r["note_id"] for r in data["results"]]
    assert note_id in result_ids


def test_search_endpoint_422_empty_q(client):
    """GET /notes/search?q= returns 422 (FastAPI Query min_length=1)."""
    resp = client.get("/notes/search", params={"q": ""})
    assert resp.status_code == 422


def test_fts_sync_on_update(client):
    """Create note, update content, old term misses, new term hits."""
    unique_old = "alpha beta gamma delta original"
    unique_new = "epsilon zeta eta theta updated"
    create = client.post("/notes", json={"content": unique_old, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    client.patch(f"/notes/{note_id}", json={"content": unique_new})

    hit = client.get("/notes/search", params={"q": "epsilon zeta"})
    assert hit.status_code == 200
    hit_ids = [r["note_id"] for r in hit.json()["results"]]
    assert note_id in hit_ids

    miss = client.get("/notes/search", params={"q": "alpha beta"})
    assert miss.status_code == 200
    miss_ids = [r["note_id"] for r in miss.json()["results"]]
    assert note_id not in miss_ids


def test_fts_sync_on_delete(client):
    """Create note, verify FTS hit, delete note, verify FTS miss."""
    create = client.post("/notes", json={"content": "Luminiferous ether hypothesis", "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    hit = client.get("/notes/search", params={"q": "Luminiferous ether"})
    assert hit.status_code == 200
    assert note_id in [r["note_id"] for r in hit.json()["results"]]

    del_resp = client.delete(f"/notes/{note_id}")
    assert del_resp.status_code == 204

    miss = client.get("/notes/search", params={"q": "Luminiferous ether"})
    assert miss.status_code == 200
    assert note_id not in [r["note_id"] for r in miss.json()["results"]]


# ---------------------------------------------------------------------------
# Slow integration test (requires all_books_ingested fixture)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_alice_note_search_slow(all_books_ingested):
    """Hybrid search with a real Alice note returns the note in top-3 results."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        content = "In Wonderland the Cheshire Cat can disappear leaving only its grin"
        create = c.post("/notes", json={"content": content, "tags": []})
        assert create.status_code == 201
        note_id = create.json()["id"]

        resp = c.get("/notes/search", params={"q": "Cheshire Cat disappear"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        top3_ids = [r["note_id"] for r in results[:3]]
        assert note_id in top3_ids, f"Note not in top-3: {[r['note_id'] for r in results]}"
