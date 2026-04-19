"""Unit tests for S175: Multi-document notes with NoteSourceModel pivot.

Tests cover:
- POST /notes with source_document_ids creates NoteSourceModel rows
- GET /notes?document_id= returns notes linked via NoteSourceModel (not just NoteModel.document_id)
- GET /notes/{id} response includes source_document_ids
- PATCH /notes/{id} syncs NoteSourceModel rows (remove old, add new)
- NoteGraphService.upsert_note_node emits DERIVED_FROM for each NoteSourceModel row
- db_init migration backfills NoteSourceModel from notes.document_id
"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_note(client, content: str, source_document_ids: list[str] | None = None) -> dict:
    payload: dict = {"content": content, "tags": []}
    if source_document_ids is not None:
        payload["source_document_ids"] = source_document_ids
    resp = client.post("/notes", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Test: POST /notes creates NoteSourceModel rows
# ---------------------------------------------------------------------------


def test_create_note_with_source_document_ids(client):
    """POST /notes with source_document_ids creates NoteSourceModel rows and returns them."""
    doc_id_1 = str(uuid.uuid4())
    doc_id_2 = str(uuid.uuid4())

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        note = _create_note(client, "cross-book annotation", [doc_id_1, doc_id_2])

    assert set(note["source_document_ids"]) == {doc_id_1, doc_id_2}
    assert note["id"] is not None


def test_create_note_without_source_document_ids_returns_empty(client):
    """POST /notes without source_document_ids returns source_document_ids=[]."""
    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        note = _create_note(client, "simple note")

    assert note["source_document_ids"] == []


# ---------------------------------------------------------------------------
# Test: GET /notes/{id} response includes source_document_ids
# ---------------------------------------------------------------------------


def test_get_note_includes_source_document_ids(client):
    """GET /notes/{id} response includes source_document_ids from NoteSourceModel."""
    doc_id_1 = str(uuid.uuid4())

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        note = _create_note(client, "test note for get", [doc_id_1])

    resp = client.get(f"/notes/{note['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert doc_id_1 in data["source_document_ids"]


# ---------------------------------------------------------------------------
# Test: GET /notes?document_id= returns notes linked via NoteSourceModel
# ---------------------------------------------------------------------------


def test_list_notes_by_document_id_via_pivot(client):
    """GET /notes?document_id={id} returns notes linked via NoteSourceModel pivot."""
    doc_id = str(uuid.uuid4())

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        # Note with null document_id but source_document_ids points to doc_id
        note = _create_note(client, "pivot-linked note", [doc_id])

    assert note["document_id"] is None  # No legacy FK set

    resp = client.get(f"/notes?document_id={doc_id}")
    assert resp.status_code == 200
    ids = [n["id"] for n in resp.json()]
    assert note["id"] in ids


def test_list_notes_by_document_id_legacy_and_pivot(client):
    """GET /notes?document_id= returns notes via both legacy FK and pivot."""
    doc_id = str(uuid.uuid4())

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        # Legacy note with document_id set directly
        legacy_note = client.post(
            "/notes",
            json={"content": "legacy note", "tags": [], "document_id": doc_id},
        ).json()
        # Pivot note with source_document_ids
        pivot_note = _create_note(client, "pivot note", [doc_id])

    resp = client.get(f"/notes?document_id={doc_id}")
    assert resp.status_code == 200
    ids = [n["id"] for n in resp.json()]
    assert legacy_note["id"] in ids
    assert pivot_note["id"] in ids


# ---------------------------------------------------------------------------
# Test: PATCH syncs NoteSourceModel rows
# ---------------------------------------------------------------------------


def test_patch_note_syncs_source_document_ids(client):
    """PATCH /notes/{id} with source_document_ids replaces pivot rows."""
    doc_id_1 = str(uuid.uuid4())
    doc_id_2 = str(uuid.uuid4())
    doc_id_3 = str(uuid.uuid4())

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        note = _create_note(client, "note to patch", [doc_id_1, doc_id_2])

        # Patch: replace with doc_id_2 + doc_id_3 (remove doc_id_1, add doc_id_3)
        with patch("app.services.vector_store.LanceDBService.delete_note_vector"):
            resp = client.patch(
                f"/notes/{note['id']}",
                json={"source_document_ids": [doc_id_2, doc_id_3]},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert set(data["source_document_ids"]) == {doc_id_2, doc_id_3}
    # doc_id_1 should be gone
    assert doc_id_1 not in data["source_document_ids"]


def test_patch_note_without_source_document_ids_does_not_change_pivot(client):
    """PATCH /notes/{id} without source_document_ids leaves pivot rows unchanged."""
    doc_id_1 = str(uuid.uuid4())

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_note_node",
        new_callable=AsyncMock,
    ):
        note = _create_note(client, "stable note", [doc_id_1])

        with patch("app.services.vector_store.LanceDBService.delete_note_vector"):
            # Patch content only -- source_document_ids NOT sent
            resp = client.patch(
                f"/notes/{note['id']}",
                json={"content": "updated content"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert doc_id_1 in data["source_document_ids"]


# ---------------------------------------------------------------------------
# Test: upsert_note_node emits DERIVED_FROM for each source_document_id
# ---------------------------------------------------------------------------


def test_upsert_note_node_emits_derived_from_for_each_source(tmp_path):
    """NoteGraphService._upsert_note_node_locked emits DERIVED_FROM for each source_document_id."""
    from app.services.graph import KuzuService
    from app.services.note_graph import NoteGraphService

    ks = KuzuService(str(tmp_path))
    svc = NoteGraphService()

    doc_id_1 = str(uuid.uuid4())
    doc_id_2 = str(uuid.uuid4())
    note_id = str(uuid.uuid4())

    # Seed two Document nodes in Kuzu
    ks._conn.execute(
        "CREATE (:Document {id: $id, title: 'Doc 1', content_type: 'book'})",
        {"id": doc_id_1},
    )
    ks._conn.execute(
        "CREATE (:Document {id: $id, title: 'Doc 2', content_type: 'book'})",
        {"id": doc_id_2},
    )

    with patch("app.services.graph.get_graph_service", return_value=ks):
        with patch(
            "app.services.note_graph.NoteGraphService._extract_entities",
            return_value=[],
        ):
            asyncio.run(
                svc.upsert_note_node(
                    note_id=note_id,
                    content="test note",
                    document_id=None,
                    tags=[],
                    source_document_ids=[doc_id_1, doc_id_2],
                )
            )

    # Verify DERIVED_FROM edges exist for both documents
    r1 = ks._conn.execute(
        "MATCH (n:Note {id: $nid})-[:DERIVED_FROM]->(d:Document {id: $did}) RETURN n.id",
        {"nid": note_id, "did": doc_id_1},
    )
    assert r1.has_next(), "DERIVED_FROM edge to doc_id_1 not found"

    r2 = ks._conn.execute(
        "MATCH (n:Note {id: $nid})-[:DERIVED_FROM]->(d:Document {id: $did}) RETURN n.id",
        {"nid": note_id, "did": doc_id_2},
    )
    assert r2.has_next(), "DERIVED_FROM edge to doc_id_2 not found"


# ---------------------------------------------------------------------------
# Test: migration backfills NoteSourceModel from notes.document_id
# ---------------------------------------------------------------------------


def test_migration_backfills_note_sources(client):
    """db_init migration backfills NoteSourceModel rows from notes.document_id."""
    from sqlalchemy import select, text

    from app.database import get_session_factory
    from app.db_init import create_all_tables
    from app.models import NoteSourceModel

    doc_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())

    async def _run():
        async with get_session_factory()() as session:
            # Insert a note with a legacy document_id directly
            await session.execute(
                text(
                    "INSERT INTO notes"
                    " (id, document_id, content, tags, archived, created_at, updated_at)"
                    " VALUES (:id, :doc_id, 'migration test', '[]', 0, :now, :now)"
                ),
                {"id": note_id, "doc_id": doc_id, "now": datetime.now(UTC).isoformat()},
            )
            await session.commit()

        # Re-run create_all_tables to trigger migration
        from app.database import get_engine

        engine = get_engine()
        await create_all_tables(engine)

        async with get_session_factory()() as session:
            row = (
                await session.execute(
                    select(NoteSourceModel).where(
                        NoteSourceModel.note_id == note_id,
                        NoteSourceModel.document_id == doc_id,
                    )
                )
            ).scalar_one_or_none()
        return row

    result = asyncio.run(_run())
    assert result is not None, "Migration did not backfill NoteSourceModel row"
    assert result.note_id == note_id
    assert result.document_id == doc_id
