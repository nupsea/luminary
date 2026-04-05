"""Tests for CRUD notes endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_note_returns_201(client):
    """POST /notes creates a note and returns 201 with full schema."""
    resp = client.post(
        "/notes",
        json={"content": "Entanglement is spooky.", "tags": ["quantum"], "group_name": "Physics"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Entanglement is spooky."
    assert data["tags"] == ["quantum"]
    assert data["group_name"] == "Physics"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_note_with_document_id(client):
    """POST /notes accepts document_id and chunk_id."""
    resp = client.post(
        "/notes",
        json={"content": "Anchored note.", "document_id": "doc-1", "chunk_id": "chunk-1"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["document_id"] == "doc-1"
    assert data["chunk_id"] == "chunk-1"


# ---------------------------------------------------------------------------
# Read / filter
# ---------------------------------------------------------------------------


def test_list_notes_returns_all(client):
    """GET /notes returns all created notes."""
    client.post("/notes", json={"content": "Note A"})
    client.post("/notes", json={"content": "Note B"})
    resp = client.get("/notes")
    assert resp.status_code == 200
    data = resp.json()
    contents = [n["content"] for n in data]
    assert "Note A" in contents
    assert "Note B" in contents


def test_list_notes_filter_by_document_id(client):
    """GET /notes?document_id=X returns only notes for that document."""
    client.post("/notes", json={"content": "For doc-X", "document_id": "doc-X"})
    client.post("/notes", json={"content": "For doc-Y", "document_id": "doc-Y"})
    resp = client.get("/notes?document_id=doc-X")
    assert resp.status_code == 200
    data = resp.json()
    assert all(n["document_id"] == "doc-X" for n in data)
    contents = [n["content"] for n in data]
    assert "For doc-X" in contents
    assert "For doc-Y" not in contents


def test_list_notes_filter_by_tag(client):
    """GET /notes?tag=T returns only notes containing that tag."""
    client.post("/notes", json={"content": "Tagged alpha", "tags": ["alpha"]})
    client.post("/notes", json={"content": "Tagged beta", "tags": ["beta"]})
    resp = client.get("/notes?tag=alpha")
    assert resp.status_code == 200
    data = resp.json()
    assert all("alpha" in n["tags"] for n in data)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_note_content_and_tags(client):
    """PUT /notes/{id} updates content and tags."""
    create_resp = client.post("/notes", json={"content": "Old content", "tags": ["old"]})
    note_id = create_resp.json()["id"]

    resp = client.put(f"/notes/{note_id}", json={"content": "New content", "tags": ["new"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "New content"
    assert data["tags"] == ["new"]


def test_update_nonexistent_note_returns_404(client):
    """PUT /notes/{id} for missing note returns 404."""
    resp = client.put("/notes/no-such-id", json={"content": "x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_note_returns_204(client):
    """DELETE /notes/{id} returns 204 and the note is gone."""
    create_resp = client.post("/notes", json={"content": "To be deleted"})
    note_id = create_resp.json()["id"]

    del_resp = client.delete(f"/notes/{note_id}")
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = client.get("/notes")
    ids = [n["id"] for n in list_resp.json()]
    assert note_id not in ids


def test_delete_nonexistent_note_returns_404(client):
    """DELETE /notes/{id} for missing note returns 404."""
    resp = client.delete("/notes/no-such-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Groups endpoint
# ---------------------------------------------------------------------------


def test_groups_returns_correct_counts(client):
    """GET /notes/groups returns groups and tags with correct counts."""
    import uuid
    # Use unique names to avoid collisions with notes from other tests
    suffix = uuid.uuid4().hex[:8]
    gname1 = f"GRP1_{suffix}"
    gname2 = f"GRP2_{suffix}"
    tag1 = f"tag1-{suffix}"
    tag2 = f"tag2-{suffix}"

    client.post("/notes", json={"content": "n1", "group_name": gname1, "tags": [tag1]})
    client.post("/notes", json={"content": "n2", "group_name": gname1, "tags": [tag1, tag2]})
    client.post("/notes", json={"content": "n3", "group_name": gname2, "tags": [tag2]})

    resp = client.get("/notes/groups")
    assert resp.status_code == 200
    data = resp.json()

    group_map = {g["name"]: g["count"] for g in data["groups"]}
    assert group_map.get(gname1) == 2
    assert group_map.get(gname2) == 1

    tag_map = {t["name"]: t["count"] for t in data["tags"]}
    assert tag_map.get(tag1) == 2
    assert tag_map.get(tag2) == 2

# ---------------------------------------------------------------------------
# section_id support (S106)
# ---------------------------------------------------------------------------


def test_create_note_with_section_id(client):
    """POST /notes with section_id stores and returns it."""
    resp = client.post(
        "/notes",
        json={"content": "Section note", "document_id": "doc-1", "section_id": "sec-42"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["section_id"] == "sec-42"


def test_list_notes_returns_section_id(client):
    """GET /notes?document_id=X returns section_id in each note object."""
    client.post(
        "/notes",
        json={"content": "Note for section", "document_id": "doc-s106", "section_id": "sec-7"},
    )
    resp = client.get("/notes?document_id=doc-s106")
    assert resp.status_code == 200
    data = resp.json()
    assert any(n["section_id"] == "sec-7" for n in data)


def test_patch_note_updates_section_id(client):
    """PATCH /notes/{id} with section_id updates it; notes without it return null."""
    create_resp = client.post("/notes", json={"content": "No section yet"})
    assert create_resp.status_code == 201
    note_id = create_resp.json()["id"]
    assert create_resp.json()["section_id"] is None  # nullable default

    patch_resp = client.patch(f"/notes/{note_id}", json={"section_id": "sec-99"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["section_id"] == "sec-99"


def test_patch_note_null_section_id_does_not_clear(client):
    """PATCH /notes/{id} with section_id=null does NOT clear it (PATCH semantics)."""
    create_resp = client.post(
        "/notes",
        json={"content": "Has section", "section_id": "sec-original"},
    )
    note_id = create_resp.json()["id"]

    # Sending null should be a no-op (cannot clear via PATCH)
    patch_resp = client.patch(f"/notes/{note_id}", json={"content": "Updated", "section_id": None})
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["content"] == "Updated"
    # section_id unchanged because None means "field not sent"
    assert data["section_id"] == "sec-original"
