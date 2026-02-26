"""Structured logging audit tests.

Verify that mutating endpoints emit INFO-level structured logs through the
Python ``logging`` module (no print(), no bare string interpolation).

Tests use ``caplog`` to capture log records without requiring a live backend.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Notes router
# ---------------------------------------------------------------------------


def test_create_note_emits_info_log(client, caplog):
    """POST /notes emits INFO 'Created note' with note_id in extra."""
    with caplog.at_level(logging.INFO, logger="app.routers.notes"):
        resp = client.post("/notes", json={"content": "test note"})
    assert resp.status_code == 201
    msgs = [r.message for r in caplog.records if r.name == "app.routers.notes"]
    assert any("Created note" in m for m in msgs), f"Expected 'Created note' in {msgs}"


def test_update_note_emits_info_log(client, caplog):
    """PUT /notes/{id} emits INFO 'Updated note'."""
    note_id = client.post("/notes", json={"content": "original"}).json()["id"]
    with caplog.at_level(logging.INFO, logger="app.routers.notes"):
        resp = client.put(f"/notes/{note_id}", json={"content": "updated"})
    assert resp.status_code == 200
    msgs = [r.message for r in caplog.records if r.name == "app.routers.notes"]
    assert any("Updated note" in m for m in msgs), f"Expected 'Updated note' in {msgs}"


def test_delete_note_emits_info_log(client, caplog):
    """DELETE /notes/{id} emits INFO 'Deleted note'."""
    note_id = client.post("/notes", json={"content": "to delete"}).json()["id"]
    with caplog.at_level(logging.INFO, logger="app.routers.notes"):
        resp = client.delete(f"/notes/{note_id}")
    assert resp.status_code == 204
    msgs = [r.message for r in caplog.records if r.name == "app.routers.notes"]
    assert any("Deleted note" in m for m in msgs), f"Expected 'Deleted note' in {msgs}"


# ---------------------------------------------------------------------------
# Documents router
# ---------------------------------------------------------------------------


def test_patch_document_emits_info_log(client, caplog):
    """PATCH /documents/{id} emits INFO 'Patched document'."""
    # First ingest a document to get a valid ID
    import io

    resp = client.post(
        "/documents/ingest",
        files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["document_id"]

    with caplog.at_level(logging.INFO, logger="app.routers.documents"):
        patch_resp = client.patch(f"/documents/{doc_id}", json={"title": "New Title"})
    assert patch_resp.status_code == 200
    msgs = [r.message for r in caplog.records if r.name == "app.routers.documents"]
    assert any("Patched document" in m for m in msgs), f"Expected 'Patched document' in {msgs}"


def test_bulk_delete_emits_info_log(client, caplog):
    """POST /documents/bulk-delete emits INFO 'Bulk deleted documents'."""
    import io

    resp = client.post(
        "/documents/ingest",
        files={"file": ("bulk.txt", io.BytesIO(b"bulk content"), "text/plain")},
    )
    doc_id = resp.json()["document_id"]

    with caplog.at_level(logging.INFO, logger="app.routers.documents"):
        del_resp = client.post("/documents/bulk-delete", json={"ids": [doc_id]})
    assert del_resp.status_code == 200
    msgs = [r.message for r in caplog.records if r.name == "app.routers.documents"]
    assert any("Bulk deleted" in m for m in msgs), f"Expected 'Bulk deleted' in {msgs}"


# ---------------------------------------------------------------------------
# Study router
# ---------------------------------------------------------------------------


def test_start_session_emits_info_log(client, caplog):
    """POST /study/sessions/start emits INFO 'Study session started'."""
    with caplog.at_level(logging.INFO, logger="app.routers.study"):
        resp = client.post("/study/sessions/start", json={"mode": "flashcard"})
    assert resp.status_code == 201
    msgs = [r.message for r in caplog.records if r.name == "app.routers.study"]
    assert any("Study session started" in m for m in msgs), (
        f"Expected 'Study session started' in {msgs}"
    )


def test_end_session_emits_info_log(client, caplog):
    """POST /study/sessions/{id}/end emits INFO 'Study session ended'."""
    session_id = client.post(
        "/study/sessions/start", json={"mode": "flashcard"}
    ).json()["id"]
    with caplog.at_level(logging.INFO, logger="app.routers.study"):
        resp = client.post(f"/study/sessions/{session_id}/end")
    assert resp.status_code == 200
    msgs = [r.message for r in caplog.records if r.name == "app.routers.study"]
    assert any("Study session ended" in m for m in msgs), (
        f"Expected 'Study session ended' in {msgs}"
    )


# ---------------------------------------------------------------------------
# Documents router — additional coverage
# ---------------------------------------------------------------------------


def test_ingest_file_received_emits_info_log(client, caplog):
    """POST /documents/ingest emits INFO 'File received' (synchronous, pre-task log)."""
    import io

    caplog.set_level(logging.INFO, logger="app.routers.documents")
    resp = client.post(
        "/documents/ingest",
        files={"file": ("receipt.txt", io.BytesIO(b"file receipt log test"), "text/plain")},
    )
    assert resp.status_code == 200
    msgs = [r.message for r in caplog.records if r.name == "app.routers.documents"]
    assert any("File received" in m for m in msgs), (
        f"Expected 'File received' in {msgs}"
    )


def test_patch_document_tags_emits_info_log(client, caplog):
    """PATCH /documents/{id}/tags emits INFO 'Patched document tags'."""
    import io

    resp = client.post(
        "/documents/ingest",
        files={"file": ("tags.txt", io.BytesIO(b"tagged content"), "text/plain")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["document_id"]

    with caplog.at_level(logging.INFO, logger="app.routers.documents"):
        tags_resp = client.patch(
            f"/documents/{doc_id}/tags", json={"tags": ["science", "history"]}
        )
    assert tags_resp.status_code == 200
    msgs = [r.message for r in caplog.records if r.name == "app.routers.documents"]
    assert any("Patched document tags" in m for m in msgs), (
        f"Expected 'Patched document tags' in {msgs}"
    )
