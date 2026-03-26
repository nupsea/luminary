"""Tests for S173: Collection health report.

Covers:
- cohesion_score: identical vectors -> 1.0; < 6 notes -> None
- uncovered_notes: note without flashcard appears; note with flashcard does not
- stale_notes: note updated_at > 90 days ago appears; recent note does not
- archive_stale: sets archived=True; archived notes excluded from GET /notes
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.collection_health import _compute_cohesion

# ---------------------------------------------------------------------------
# Pure unit tests -- no DB required
# ---------------------------------------------------------------------------


def test_cohesion_identical_vectors():
    """6 identical unit vectors -> cosine similarity 1.0 everywhere."""
    v = [1.0, 0.0, 0.0]
    vectors = [v] * 6
    score = _compute_cohesion(vectors)
    assert score is not None
    assert abs(score - 1.0) < 1e-5


def test_cohesion_orthogonal_vectors():
    """Two orthogonal unit vectors (padded to 6) -> mean similarity close to 0."""
    # Build 6 orthogonal vectors (identity basis repeated as needed)
    dim = 6
    vecs = []
    for i in range(6):
        v = [0.0] * dim
        v[i % dim] = 1.0
        vecs.append(v)
    score = _compute_cohesion(vecs)
    # All pairs are orthogonal -> mean similarity = 0
    assert score is not None
    assert abs(score) < 1e-5


def test_cohesion_fewer_than_6_returns_none():
    """< 6 vectors returns None (insufficient data)."""
    v = [1.0, 0.0, 0.0]
    assert _compute_cohesion([v] * 5) is None
    assert _compute_cohesion([]) is None


# ---------------------------------------------------------------------------
# Integration tests via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_collection(client, name="TestColl") -> dict:
    resp = client.post("/collections", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


def _create_note(client, content="hello world", archived=False) -> dict:
    resp = client.post(
        "/notes",
        json={"content": content},
    )
    assert resp.status_code == 201
    return resp.json()


def _add_note_to_collection(client, collection_id: str, note_id: str):
    resp = client.post(
        f"/collections/{collection_id}/notes",
        json={"note_ids": [note_id]},
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /collections/{id}/health
# ---------------------------------------------------------------------------


def test_health_returns_expected_shape(client):
    """GET /collections/{id}/health returns 200 with all required keys."""
    coll = _create_collection(client, "HealthShape")
    resp = client.get(f"/collections/{coll['id']}/health")
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "collection_id",
        "collection_name",
        "cohesion_score",
        "note_count",
        "orphaned_notes",
        "uncovered_notes",
        "stale_notes",
        "hotspot_tags",
    ]:
        assert key in data, f"Missing key: {key}"


def test_health_404_for_missing_collection(client):
    resp = client.get(f"/collections/{uuid.uuid4()}/health")
    assert resp.status_code == 404


def test_cohesion_none_when_fewer_than_6_notes(client):
    """Collection with < 6 notes must return cohesion_score=null."""
    coll = _create_collection(client, "FewNotes")
    for i in range(3):
        note = _create_note(client, f"note {i}")
        _add_note_to_collection(client, coll["id"], note["id"])

    # Mock LanceDB fetch to return empty (no vectors stored in test)
    resp = client.get(f"/collections/{coll['id']}/health")
    assert resp.status_code == 200
    assert resp.json()["cohesion_score"] is None


def test_uncovered_notes_appears_in_report(client):
    """A note in a collection with no flashcard should appear in uncovered_notes."""
    coll = _create_collection(client, "UncoveredTest")
    note = _create_note(client, "Some learning content")
    _add_note_to_collection(client, coll["id"], note["id"])

    resp = client.get(f"/collections/{coll['id']}/health")
    assert resp.status_code == 200
    data = resp.json()
    uncovered_ids = [u["note_id"] for u in data["uncovered_notes"]]
    assert note["id"] in uncovered_ids


def test_covered_note_absent_from_uncovered(client):
    """A note that has a matching flashcard (source='note', deck=coll.name) should not appear."""
    from sqlalchemy import text as sa_text

    from app.database import get_session_factory

    coll = _create_collection(client, "CoveredTest")
    note = _create_note(client, "Covered note content")
    _add_note_to_collection(client, coll["id"], note["id"])

    # Insert a flashcard row manually that satisfies coverage
    import asyncio

    async def _insert_card():
        async with get_session_factory()() as session:
            await session.execute(
                sa_text(
                    "INSERT INTO flashcards"
                    " (id, source, deck, note_id, question, answer,"
                    "  source_excerpt, difficulty, is_user_edited, fsrs_state,"
                    "  fsrs_stability, fsrs_difficulty, reps, lapses, created_at)"
                    " VALUES (:id, 'note', :deck, :note_id, 'Q', 'A', '', 'medium',"
                    "  0, 'new', 0.0, 0.0, 0, 0, datetime('now'))"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "deck": coll["name"],
                    "note_id": note["id"],
                },
            )
            await session.commit()

    asyncio.get_event_loop().run_until_complete(_insert_card())

    resp = client.get(f"/collections/{coll['id']}/health")
    assert resp.status_code == 200
    uncovered_ids = [u["note_id"] for u in resp.json()["uncovered_notes"]]
    assert note["id"] not in uncovered_ids


def test_stale_note_appears_in_report(client):
    """A note updated more than 90 days ago should appear in stale_notes."""
    from sqlalchemy import text as sa_text

    from app.database import get_session_factory

    coll = _create_collection(client, "StaleTest")
    note = _create_note(client, "Old content")
    _add_note_to_collection(client, coll["id"], note["id"])

    # Force updated_at to 91 days ago
    stale_dt = (datetime.now(UTC) - timedelta(days=91)).isoformat()

    import asyncio

    async def _age_note():
        async with get_session_factory()() as session:
            await session.execute(
                sa_text("UPDATE notes SET updated_at = :dt WHERE id = :nid"),
                {"dt": stale_dt, "nid": note["id"]},
            )
            await session.commit()

    asyncio.get_event_loop().run_until_complete(_age_note())

    resp = client.get(f"/collections/{coll['id']}/health")
    assert resp.status_code == 200
    stale_ids = [s["note_id"] for s in resp.json()["stale_notes"]]
    assert note["id"] in stale_ids


def test_recent_note_not_stale(client):
    """A note updated recently should not appear in stale_notes."""
    coll = _create_collection(client, "FreshTest")
    note = _create_note(client, "Fresh content")
    _add_note_to_collection(client, coll["id"], note["id"])

    resp = client.get(f"/collections/{coll['id']}/health")
    assert resp.status_code == 200
    stale_ids = [s["note_id"] for s in resp.json()["stale_notes"]]
    assert note["id"] not in stale_ids


# ---------------------------------------------------------------------------
# POST /collections/{id}/health/archive-stale
# ---------------------------------------------------------------------------


def test_archive_stale_sets_archived_and_excludes_from_list(client):
    """archive-stale sets archived=True; GET /notes excludes archived notes."""
    from sqlalchemy import text as sa_text

    from app.database import get_session_factory

    coll = _create_collection(client, "ArchiveTest")
    note = _create_note(client, "Very old note")
    _add_note_to_collection(client, coll["id"], note["id"])

    # Age the note to stale
    stale_dt = (datetime.now(UTC) - timedelta(days=91)).isoformat()

    import asyncio

    async def _age():
        async with get_session_factory()() as session:
            await session.execute(
                sa_text("UPDATE notes SET updated_at = :dt WHERE id = :nid"),
                {"dt": stale_dt, "nid": note["id"]},
            )
            await session.commit()

    asyncio.get_event_loop().run_until_complete(_age())

    # Archive stale notes
    resp = client.post(f"/collections/{coll['id']}/health/archive-stale")
    assert resp.status_code == 200
    data = resp.json()
    assert "archived" in data
    assert data["archived"] >= 1

    # GET /notes should no longer include this note
    notes_resp = client.get("/notes")
    assert notes_resp.status_code == 200
    note_ids = [n["id"] for n in notes_resp.json()]
    assert note["id"] not in note_ids


def test_archive_stale_404_for_missing_collection(client):
    resp = client.post(f"/collections/{uuid.uuid4()}/health/archive-stale")
    assert resp.status_code == 404
