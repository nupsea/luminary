"""Unit tests for S171: Note-to-note bidirectional links."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_note(client, content: str) -> dict:
    resp = client.post("/notes", json={"content": content, "tags": []})
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /notes/{id}/links
# ---------------------------------------------------------------------------


def test_create_link_returns_201(client):
    """POST creates NoteLinkModel row and returns 201."""
    src = _create_note(client, "source note content")
    tgt = _create_note(client, "target note content")

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_links_to_edge",
        new_callable=AsyncMock,
    ):
        resp = client.post(
            f"/notes/{src['id']}/links",
            json={"target_note_id": tgt["id"], "link_type": "elaborates"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["note_id"] == tgt["id"]
    assert data["link_type"] == "elaborates"
    assert "id" in data


def test_create_link_404_source_missing(client):
    """Returns 404 when source note does not exist."""
    tgt = _create_note(client, "target note")
    resp = client.post(
        f"/notes/{uuid.uuid4()}/links",
        json={"target_note_id": tgt["id"], "link_type": "see-also"},
    )
    assert resp.status_code == 404


def test_create_link_404_target_missing(client):
    """Returns 404 when target note does not exist."""
    src = _create_note(client, "source note")
    resp = client.post(
        f"/notes/{src['id']}/links",
        json={"target_note_id": str(uuid.uuid4()), "link_type": "see-also"},
    )
    assert resp.status_code == 404


def test_create_link_409_duplicate(client):
    """Returns 409 when the same (source, target, link_type) triple exists."""
    src = _create_note(client, "source note")
    tgt = _create_note(client, "target note")

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_links_to_edge",
        new_callable=AsyncMock,
    ):
        client.post(
            f"/notes/{src['id']}/links",
            json={"target_note_id": tgt["id"], "link_type": "supports"},
        )
        resp = client.post(
            f"/notes/{src['id']}/links",
            json={"target_note_id": tgt["id"], "link_type": "supports"},
        )

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /notes/{id}/links/{target_id}
# ---------------------------------------------------------------------------


def test_delete_link_returns_204(client):
    """DELETE removes the link row and returns 204."""
    src = _create_note(client, "source note")
    tgt = _create_note(client, "target note")

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_links_to_edge",
        new_callable=AsyncMock,
    ):
        client.post(
            f"/notes/{src['id']}/links",
            json={"target_note_id": tgt["id"], "link_type": "see-also"},
        )

    with patch(
        "app.services.note_graph.NoteGraphService.delete_links_to_edge",
        new_callable=AsyncMock,
    ):
        resp = client.delete(f"/notes/{src['id']}/links/{tgt['id']}?link_type=see-also")

    assert resp.status_code == 204


def test_delete_link_404_not_found(client):
    """Returns 404 when link does not exist."""
    src = _create_note(client, "source note")
    resp = client.delete(f"/notes/{src['id']}/links/{uuid.uuid4()}?link_type=see-also")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /notes/{id}/links (3-note chain)
# ---------------------------------------------------------------------------


def test_get_links_3_note_chain(client):
    """GET /links returns correct outgoing and incoming for a 3-note chain A->B->C."""
    note_a = _create_note(client, "Note A content")
    note_b = _create_note(client, "Note B content")
    note_c = _create_note(client, "Note C content")

    with patch(
        "app.services.note_graph.NoteGraphService.upsert_links_to_edge",
        new_callable=AsyncMock,
    ):
        client.post(
            f"/notes/{note_a['id']}/links",
            json={"target_note_id": note_b["id"], "link_type": "elaborates"},
        )
        client.post(
            f"/notes/{note_b['id']}/links",
            json={"target_note_id": note_c["id"], "link_type": "see-also"},
        )

    # A: 1 outgoing, 0 incoming
    resp_a = client.get(f"/notes/{note_a['id']}/links")
    assert resp_a.status_code == 200
    a_data = resp_a.json()
    assert len(a_data["outgoing"]) == 1
    assert len(a_data["incoming"]) == 0
    assert a_data["outgoing"][0]["note_id"] == note_b["id"]

    # B: 1 outgoing, 1 incoming
    resp_b = client.get(f"/notes/{note_b['id']}/links")
    b_data = resp_b.json()
    assert len(b_data["outgoing"]) == 1
    assert len(b_data["incoming"]) == 1
    assert b_data["outgoing"][0]["note_id"] == note_c["id"]
    assert b_data["incoming"][0]["note_id"] == note_a["id"]

    # C: 0 outgoing, 1 incoming
    resp_c = client.get(f"/notes/{note_c['id']}/links")
    c_data = resp_c.json()
    assert len(c_data["outgoing"]) == 0
    assert len(c_data["incoming"]) == 1
    assert c_data["incoming"][0]["note_id"] == note_b["id"]


# ---------------------------------------------------------------------------
# GET /notes/autocomplete
# ---------------------------------------------------------------------------


def test_autocomplete_returns_matching_notes(client):
    """GET /notes/autocomplete?q= returns up to 8 notes by content prefix."""
    suffix = uuid.uuid4().hex[:6]
    for i in range(3):
        _create_note(client, f"prefix_{suffix}_{i} some content")
    _create_note(client, "other content not matching")

    resp = client.get(f"/notes/autocomplete?q=prefix_{suffix}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    for item in data:
        assert "id" in item
        assert "preview" in item


def test_autocomplete_limit_8(client):
    """GET /notes/autocomplete returns at most 8 results."""
    suffix = uuid.uuid4().hex[:6]
    for i in range(10):
        _create_note(client, f"many_{suffix}_{i} content")

    resp = client.get(f"/notes/autocomplete?q=many_{suffix}")
    assert resp.status_code == 200
    assert len(resp.json()) <= 8
