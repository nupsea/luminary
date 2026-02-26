"""Fast CRUD tests for Notes API — all use in-memory SQLite from conftest.

These complement test_notes.py by covering PATCH and the specific acceptance
criteria in S50 (field names, response shapes, 404 for missing notes).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_create_note(client):
    """POST /notes with content+tags → 201, response has id, content, created_at."""
    resp = client.post(
        "/notes",
        json={"document_id": None, "content": "test note", "tags": []},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data["id"], str)
    assert data["content"] == "test note"
    assert isinstance(data["created_at"], str)


def test_list_notes(client):
    """GET /notes returns all created notes."""
    import uuid

    suffix = uuid.uuid4().hex[:8]
    client.post("/notes", json={"content": f"note_a_{suffix}", "tags": []})
    client.post("/notes", json={"content": f"note_b_{suffix}", "tags": []})

    resp = client.get("/notes")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert f"note_a_{suffix}" in contents
    assert f"note_b_{suffix}" in contents


def test_update_note(client):
    """PATCH /notes/{id} updates content correctly."""
    create = client.post("/notes", json={"content": "original content", "tags": []})
    note_id = create.json()["id"]

    resp = client.patch(f"/notes/{note_id}", json={"content": "updated content"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated content"


def test_delete_note(client):
    """DELETE /notes/{id} returns 204 and the note is absent from list."""
    create = client.post("/notes", json={"content": "to be deleted", "tags": []})
    note_id = create.json()["id"]

    del_resp = client.delete(f"/notes/{note_id}")
    assert del_resp.status_code == 204

    list_resp = client.get("/notes")
    ids = [n["id"] for n in list_resp.json()]
    assert note_id not in ids


def test_note_not_found(client):
    """PATCH and DELETE on nonexistent note_id return 404."""
    resp_patch = client.patch("/notes/nonexistent-id", json={"content": "x"})
    assert resp_patch.status_code == 404

    resp_delete = client.delete("/notes/nonexistent-id")
    assert resp_delete.status_code == 404
