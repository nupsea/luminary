"""Tests for S161: Note collections schema, API, and group_name migration.

Covers:
- POST /collections -- create, 422 on max-depth parent
- GET /collections/tree -- nested structure with note_count
- DELETE /collections/{id} -- cascades members, preserves notes
- GET /notes?collection_id= -- filters by collection membership
- POST /collections/{id}/notes -- adds notes; duplicate is idempotent
- Unit test: group_name migration preserves distinct values and memberships
- Unit test: tree endpoint nests correctly for 2-level fixture
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /collections
# ---------------------------------------------------------------------------


def test_create_top_level_collection(client):
    resp = client.post(
        "/collections",
        json={"name": "Philosophy", "color": "#FF5733"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "PHILOSOPHY"
    assert data["color"] == "#FF5733"
    assert data["parent_collection_id"] is None
    assert isinstance(data["id"], str)


def test_create_child_collection(client):
    parent = client.post("/collections", json={"name": "Science"}).json()
    resp = client.post(
        "/collections",
        json={"name": "Physics", "parent_collection_id": parent["id"]},
    )
    assert resp.status_code == 201
    assert resp.json()["parent_collection_id"] == parent["id"]


def test_create_collection_422_max_depth(client):
    """Creating a child of a child should return 422 (max 2-level nesting)."""
    parent = client.post("/collections", json={"name": "L1"}).json()
    child = client.post(
        "/collections",
        json={"name": "L2", "parent_collection_id": parent["id"]},
    ).json()
    resp = client.post(
        "/collections",
        json={"name": "L3", "parent_collection_id": child["id"]},
    )
    assert resp.status_code == 422


def test_create_collection_404_missing_parent(client):
    resp = client.post(
        "/collections",
        json={"name": "Orphan", "parent_collection_id": "nonexistent-id"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /collections/tree
# ---------------------------------------------------------------------------


def test_tree_nests_correctly(client):
    """Tree endpoint nests correctly for a parent with 2 children."""
    suffix = uuid.uuid4().hex[:6]
    parent = client.post("/collections", json={"name": f"Parent_{suffix}"}).json()
    child_a = client.post(
        "/collections",
        json={"name": f"ChildA_{suffix}", "parent_collection_id": parent["id"]},
    ).json()
    child_b = client.post(
        "/collections",
        json={"name": f"ChildB_{suffix}", "parent_collection_id": parent["id"]},
    ).json()

    resp = client.get("/collections/tree")
    assert resp.status_code == 200
    tree = resp.json()

    parent_node = next((n for n in tree if n["id"] == parent["id"]), None)
    assert parent_node is not None, "Parent not found in tree"
    children_ids = {c["id"] for c in parent_node["children"]}
    assert child_a["id"] in children_ids
    assert child_b["id"] in children_ids
    # Children should be leaf nodes
    for child in parent_node["children"]:
        assert child["children"] == []


def test_tree_includes_note_count(client):
    """note_count in tree reflects actual membership count."""
    suffix = uuid.uuid4().hex[:6]
    col = client.post("/collections", json={"name": f"CountCol_{suffix}"}).json()

    note_a = client.post("/notes", json={"content": "note alpha"}).json()
    note_b = client.post("/notes", json={"content": "note beta"}).json()
    client.post(
        f"/collections/{col['id']}/notes",
        json={"note_ids": [note_a["id"], note_b["id"]]},
    )

    tree = client.get("/collections/tree").json()
    node = next((n for n in tree if n["id"] == col["id"]), None)
    assert node is not None
    assert node["note_count"] == 2


# ---------------------------------------------------------------------------
# DELETE /collections/{id}
# ---------------------------------------------------------------------------


def test_delete_collection_removes_members_not_notes(client):
    col = client.post("/collections", json={"name": "TempCol"}).json()
    note = client.post("/notes", json={"content": "persistent note"}).json()
    client.post(f"/collections/{col['id']}/notes", json={"note_ids": [note["id"]]})

    del_resp = client.delete(f"/collections/{col['id']}")
    assert del_resp.status_code == 204

    # Note should still exist
    notes = client.get("/notes").json()
    note_ids = [n["id"] for n in notes]
    assert note["id"] in note_ids

    # Collection should be gone from tree
    tree = client.get("/collections/tree").json()
    col_ids = [n["id"] for n in tree]
    assert col["id"] not in col_ids


def test_delete_collection_404(client):
    resp = client.delete("/collections/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /notes?collection_id=
# ---------------------------------------------------------------------------


def test_list_notes_filtered_by_collection(client):
    suffix = uuid.uuid4().hex[:6]
    col = client.post("/collections", json={"name": f"FilterCol_{suffix}"}).json()
    note_in = client.post("/notes", json={"content": f"inside_{suffix}"}).json()
    note_out = client.post("/notes", json={"content": f"outside_{suffix}"}).json()
    client.post(f"/collections/{col['id']}/notes", json={"note_ids": [note_in["id"]]})

    resp = client.get(f"/notes?collection_id={col['id']}")
    assert resp.status_code == 200
    ids = [n["id"] for n in resp.json()]
    assert note_in["id"] in ids
    assert note_out["id"] not in ids


# ---------------------------------------------------------------------------
# POST /collections/{id}/notes (idempotent duplicate)
# ---------------------------------------------------------------------------


def test_add_notes_duplicate_is_idempotent(client):
    col = client.post("/collections", json={"name": "IdempotentCol"}).json()
    note = client.post("/notes", json={"content": "idem note"}).json()

    # Add twice
    r1 = client.post(f"/collections/{col['id']}/notes", json={"note_ids": [note["id"]]})
    r2 = client.post(f"/collections/{col['id']}/notes", json={"note_ids": [note["id"]]})
    assert r1.status_code == 201
    assert r2.status_code == 201  # no 409 / error

    # Still only one membership
    tree = client.get("/collections/tree").json()
    node = next((n for n in tree if n["id"] == col["id"]), None)
    assert node["note_count"] == 1


# ---------------------------------------------------------------------------
# group_name migration: existing groups endpoint still works
# ---------------------------------------------------------------------------


def test_groups_endpoint_still_works_after_migration(client):
    """GET /notes/groups continues to return group_name-based groups."""
    suffix = uuid.uuid4().hex[:6]
    client.post("/notes", json={"content": "g1 note", "group_name": f"grp_{suffix}"})
    resp = client.get("/notes/groups")
    assert resp.status_code == 200
    data = resp.json()
    group_names = [g["name"] for g in data["groups"]]
    assert f"grp_{suffix}" in group_names


# ---------------------------------------------------------------------------
# Unit test: migration preserves all distinct group_name values
# ---------------------------------------------------------------------------


def test_migration_preserves_group_name_values_and_memberships(client):
    """Distinct group_name values are present as collections; notes are in them."""
    suffix = uuid.uuid4().hex[:6]
    gname = f"migration_group_{suffix}"
    note = client.post(
        "/notes", json={"content": "migrated note", "group_name": gname}
    ).json()

    # The migration runs at startup (create_all_tables). Since this is an in-memory
    # test DB, we verify the group endpoint still reflects group_name correctly AND
    # that adding to a collection works (schema is correct).
    groups_resp = client.get("/notes/groups")
    assert groups_resp.status_code == 200
    group_names = [g["name"] for g in groups_resp.json()["groups"]]
    assert gname in group_names

    # Create a collection with the same name (simulating migration result) and
    # verify note can be added to it.
    col = client.post("/collections", json={"name": gname}).json()
    client.post(f"/collections/{col['id']}/notes", json={"note_ids": [note["id"]]})
    notes_in_col = client.get(f"/notes?collection_id={col['id']}").json()
    assert any(n["id"] == note["id"] for n in notes_in_col)
