"""`POST /collections/migrate-naming` survives a collection deleted mid-run.

The migration reads every collection once, groups them by normalised name, then
merges each group -- deleting the losers and their children as it goes. A child
of one group's loser can itself be a member of a later group, and renaming it
there raised `sqlalchemy.exc.InvalidRequestError: Instance has been deleted`,
returning 500 from an endpoint whose entire purpose is to be safe to run.

Found by S199, which calls the migration on a real library.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _add_member(client, collection_id: str, member_id: str) -> None:
    resp = client.post(
        f"/collections/{collection_id}/members",
        json={"member_ids": [member_id], "member_type": "document"},
    )
    assert resp.status_code in (200, 201), resp.text


def _make(client, name: str, parent: str | None = None) -> str:
    body: dict = {"name": name, "color": "#6366F1"}
    if parent:
        body["parent_collection_id"] = parent
    resp = client.post("/collections", json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def test_migration_survives_a_child_deleted_by_an_earlier_group(client):
    """Two collections collapse to one name; the loser owns a child that also
    collides with a second pair. Merging the first group deletes that child, and
    the second group must not then try to rename it."""
    # Group A: two names that normalise together. a1 holds a member so it wins
    # the keeper contest and a2 is deleted, taking its child with it.
    a1 = _make(client, "migration probe alpha")
    a2 = _make(client, "Migration_Probe_Alpha")
    _add_member(client, a1, "doc-keeps-alpha-1")

    # A child under each, colliding with each other -- group B. a2's child holds
    # two members so it would be group B's keeper: the migration reaches it after
    # group A has already deleted it, and renaming a deleted instance is the 500.
    _make(client, "migration probe beta", parent=a1)
    b2 = _make(client, "Migration_Probe_Beta", parent=a2)
    _add_member(client, b2, "doc-beta-1")
    _add_member(client, b2, "doc-beta-2")

    resp = client.post("/collections/migrate-naming")
    assert resp.status_code == 200, (
        f"migration returned {resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    assert "renamed" in body and "merged" in body

    # Running it again is a no-op rather than an error: it is a migration.
    again = client.post("/collections/migrate-naming")
    assert again.status_code == 200, again.text

    names = [c["name"] for c in client.get("/collections/tree").json()]
    assert names.count("MIGRATION-PROBE-ALPHA") <= 1, "duplicates survived the merge"


def test_migration_is_a_no_op_on_already_normalised_names(client):
    """Nothing to rename, nothing to merge, and still a 200."""
    _make(client, "ALREADY-NORMAL")
    resp = client.post("/collections/migrate-naming")
    assert resp.status_code == 200, resp.text
    assert resp.json()["renamed"] == 0
