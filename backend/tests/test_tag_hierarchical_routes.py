"""A hierarchical tag can be reached by every route that takes a tag id.

`POST /tags` normalises `Science/Cell_Division` to `science/cell-division` --
hierarchy is the feature, and the Notes tab filters on it by prefix. But the
routes taking `{tag_id}` matched a single path segment, so the API minted ids it
could not then address: `DELETE /tags/science/cell-division` was a 404, and so
were the rename and the two read routes. Percent-encoding does not rescue it,
because Starlette decodes the path before matching.

The smoke suite found this the slow way: S199 created that tag, never deleted
it, and every later run failed with 409 on a tag its own cleanup could not
remove.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def hierarchical_tag(client):
    """A two-level tag, created the way the product creates one."""
    client.delete("/tags/probe/nested-child")
    resp = client.post(
        "/tags", json={"id": "Probe/Nested_Child", "display_name": "Nested Child"}
    )
    assert resp.status_code == 201, resp.text
    tag_id = resp.json()["id"]
    assert "/" in tag_id, f"expected a hierarchical id, got {tag_id!r}"
    yield tag_id
    client.delete(f"/tags/{tag_id}")


def test_a_hierarchical_tag_can_be_read(client, hierarchical_tag):
    resp = client.get(f"/tags/{hierarchical_tag}/notes")
    assert resp.status_code == 200, (
        f"GET /tags/{hierarchical_tag}/notes returned {resp.status_code}; a tag id "
        "with a slash in it must still resolve"
    )


def test_a_hierarchical_tag_can_be_renamed(client, hierarchical_tag):
    resp = client.put(f"/tags/{hierarchical_tag}", json={"display_name": "Renamed Child"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Renamed Child"


def test_a_hierarchical_tag_can_be_deleted(client, hierarchical_tag):
    """The one that bit: a tag the product can create and cannot remove."""
    resp = client.delete(f"/tags/{hierarchical_tag}")
    assert resp.status_code == 204, (
        f"DELETE /tags/{hierarchical_tag} returned {resp.status_code}; the API "
        "normalises ids into this shape, so it has to accept them back"
    )
    # `/notes` lists notes by prefix and answers [] for an unknown tag by design,
    # so the tag list is what says the tag is gone.
    remaining = [t["id"] for t in client.get("/tags").json()]
    assert hierarchical_tag not in remaining


def test_a_flat_tag_still_works(client):
    """The greedy path parameter must not change the single-segment case."""
    client.delete("/tags/probe-flat")
    assert client.post(
        "/tags", json={"id": "probe-flat", "display_name": "Probe Flat"}
    ).status_code == 201
    assert client.delete("/tags/probe-flat").status_code == 204


def test_the_literal_routes_still_win(client):
    """`{tag_id:path}` is greedy, so /tags/tree and friends must stay above it."""
    for path in ("/tags/tree", "/tags/graph", "/tags/autocomplete?q=a"):
        resp = client.get(path)
        assert resp.status_code == 200, (
            f"{path} returned {resp.status_code} -- the greedy tag route is "
            "shadowing a literal one"
        )
