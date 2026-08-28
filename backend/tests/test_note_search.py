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

# Unit tests (pure functions — no I/O)


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


# Integration + API tests (use TestClient(app) — lifespan creates in-memory DB)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Isolated TestClient with a fresh DATA_DIR per test."""
    data_dir = str(tmp_path)
    monkeypatch.setenv("DATA_DIR", data_dir)

    # Reset singletons to use the new data_dir
    import app.database as db_module
    import app.services.vector_store as vs_module
    from app.config import get_settings

    get_settings.cache_clear()
    db_module._engine = None
    db_module._session_factory = None
    vs_module._lancedb_service = None

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
    """Create note, update content, old term misses, new term hits.

    Uses semantically dissimilar content so that the vector search arm
    does not produce false-positive matches after the update.
    """
    unique_old = "photosynthesis chloroplast cellular respiration"
    unique_new = "baroque fugue counterpoint harpsichord sonata"
    create = client.post("/notes", json={"content": unique_old, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    client.patch(f"/notes/{note_id}", json={"content": unique_new})

    hit = client.get("/notes/search", params={"q": "baroque fugue"})
    assert hit.status_code == 200
    hit_ids = [r["note_id"] for r in hit.json()["results"]]
    assert note_id in hit_ids

    miss = client.get("/notes/search", params={"q": "photosynthesis chloroplast"})
    assert miss.status_code == 200
    results = miss.json()["results"]
    miss_ids = [r["note_id"] for r in results]
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


# Slow integration test (requires all_books_ingested fixture)


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


# A ghost vector is a row in the LanceDB note table whose note no longer exists
# in `notes`. `delete_note_vector` swallows its exceptions by design, so one is
# reachable in production whenever the vector store hiccups during a delete --
# which is why these tests inject one directly instead of hoping a delete fails.


def _await_embedding(note_id: str, timeout: float = 120.0) -> None:
    """Block until `POST /notes`'s background embed has written this note's vector.

    Waits for the app's own task rather than writing the vector here. Writing it
    from the test thread races that task on the same LanceDB table and CI hit the
    losing side: `Commit conflict for version 2: this Update transaction is
    incompatible with concurrent transaction Overwrite`. It passed locally three
    times first -- the race is real either way, and only one writer is correct.

    Needed only by the tests whose query shares no word with the note, where the
    FTS arm cannot answer and the semantic arm is the whole point.
    """
    import time

    from app.services.vector_store import get_lancedb_service

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        table = get_lancedb_service()._get_or_create_note_table()
        if table.count_rows() and any(
            r["note_id"] == note_id for r in table.search().limit(10_000).to_list()
        ):
            return
        time.sleep(0.5)
    raise AssertionError(
        f"note {note_id} was never embedded within {timeout}s -- the background "
        "task in POST /notes did not write its vector"
    )


def _inject_ghost_vector(content: str) -> str:
    """Put a vector in the note table for a note_id that has no `notes` row."""
    import uuid as _uuid

    from app.services.embedder import get_embedding_service
    from app.services.vector_store import get_lancedb_service

    ghost_id = f"ghost-{_uuid.uuid4()}"
    vector = get_embedding_service().encode([content])[0]
    get_lancedb_service().upsert_note_vector(ghost_id, None, content, vector)
    return ghost_id


def test_a_deleted_note_cannot_come_back_through_the_semantic_arm(client):
    """The defect this file's delete test only caught by luck.

    The FTS arm joins `notes_fts` against `notes`, so it can never serve a
    deleted note. The semantic arm read LanceDB directly and had no such join,
    so anything left in that table was returned as a live note.
    """
    content = "Luminiferous ether hypothesis and the Michelson Morley experiment"
    ghost_id = _inject_ghost_vector(content)

    resp = client.get("/notes/search", params={"q": "Luminiferous ether"})
    assert resp.status_code == 200
    assert ghost_id not in [r["note_id"] for r in resp.json()["results"]]


def test_the_semantic_arm_still_matches_without_a_word_in_common(client):
    """The floor must not become the literal-term filter it replaced.

    "feline that disappears" shares no word with the note and scores 0.7516, so
    a check for query terms in the content -- the previous behaviour -- dropped
    exactly the hit the semantic arm exists to produce.
    """
    content = "Cheshire Cat can vanish leaving only its grin"
    create = client.post("/notes", json={"content": content, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]
    _await_embedding(note_id)

    resp = client.get("/notes/search", params={"q": "feline that disappears"})
    assert resp.status_code == 200
    assert note_id in [r["note_id"] for r in resp.json()["results"]]


def test_an_unrelated_note_is_below_the_similarity_floor(client):
    """`limit(k)` has no floor, so in a library smaller than k the semantic arm
    returns every note however unrelated. 0.5004 is the measured similarity of
    this pair and it must not clear NOTE_SEMANTIC_MIN_SIMILARITY."""
    create = client.post(
        "/notes", json={"content": "baroque fugue counterpoint harpsichord sonata", "tags": []}
    )
    assert create.status_code == 201
    note_id = create.json()["id"]

    resp = client.get("/notes/search", params={"q": "photosynthesis chloroplast"})
    assert resp.status_code == 200
    assert note_id not in [r["note_id"] for r in resp.json()["results"]]


def test_the_floor_sits_between_the_two_cases_that_set_it():
    """Bracketing, so a future tweak has to move one of these to justify itself."""
    from app.services.note_search import NOTE_SEMANTIC_MIN_SIMILARITY

    assert 0.5004 < NOTE_SEMANTIC_MIN_SIMILARITY < 0.7516


def test_a_semantic_hit_carries_the_notes_own_tags(client):
    """The vector arm reported tags=[] and group_name=None for every hit,
    because it read them from the vector table, which stores neither."""
    create = client.post(
        "/notes",
        json={"content": "Cheshire Cat can vanish leaving only its grin", "tags": ["wonderland"]},
    )
    assert create.status_code == 201
    note_id = create.json()["id"]
    _await_embedding(note_id)

    resp = client.get("/notes/search", params={"q": "feline that disappears"})
    assert resp.status_code == 200
    hit = next(r for r in resp.json()["results"] if r["note_id"] == note_id)
    assert hit["tags"] == ["wonderland"]
