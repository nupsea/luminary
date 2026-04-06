"""Tests for S174: Export collections as Obsidian Markdown vault and Anki deck.

Covers:
- export_collection_markdown: 3-note collection -> zip with 3 .md files, correct frontmatter
- [[id|text]] markers converted to [[target title]] wikilinks; unresolvable -> plain text
- export_collection_anki: returns non-empty bytes parseable as a zip (apkg is a zip)
- GET /collections/{id}/export?format=markdown -> 200 with Content-Type application/zip
- GET /collections/{id}/export?format=anki -> 200 with Content-Disposition attachment
- Empty collection: both exports return valid minimal output
"""

import io
import uuid
import zipfile
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.export_service import (
    _build_yaml_frontmatter,
    _note_title,
    _resolve_links,
    _slugify,
)

# ---------------------------------------------------------------------------
# Pure unit tests (no DB)
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert _slugify("Quantum Mechanics!") == "quantum-mechanics"


def test_slugify_empty():
    result = _slugify("")
    assert result == "note"


def test_note_title_from_heading():
    note = MagicMock()
    note.content = "# My Amazing Note\nSome body text."
    note.id = "abc12345-0000-0000-0000-000000000000"
    assert _note_title(note) == "My Amazing Note"


def test_note_title_from_plain():
    note = MagicMock()
    note.content = "Just plain text."
    note.id = "abc12345-0000-0000-0000-000000000000"
    assert _note_title(note) == "Just plain text."


def test_resolve_links_converts_known_id():
    id_to_title = {"abc12345-0000-0000-0000-000000000000": "Quantum Entanglement"}
    content = "See [[abc12345-0000-0000-0000-000000000000|this note]] for details."
    result = _resolve_links(content, id_to_title)
    assert result == "See [[Quantum Entanglement]] for details."


def test_resolve_links_unresolvable_id_renders_plain_text():
    id_to_title: dict = {}
    content = "Ref [[deadbeef-0000-0000-0000-000000000000|missing]] here."
    result = _resolve_links(content, id_to_title)
    assert result == "Ref missing here."


def test_resolve_links_no_links():
    id_to_title: dict = {}
    content = "Plain content with no links."
    result = _resolve_links(content, id_to_title)
    assert result == content


def test_build_yaml_frontmatter_includes_tags_and_path():
    note = MagicMock()
    note.tags = ["physics", "quantum"]
    note.created_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
    frontmatter = _build_yaml_frontmatter(note, ["Science", "Physics"], "The Time Machine")
    assert "tags:" in frontmatter
    assert "  - physics" in frontmatter
    assert "collections:" in frontmatter
    assert "  - Science" in frontmatter
    assert "source_document: The Time Machine" in frontmatter
    assert frontmatter.startswith("---")
    assert frontmatter.endswith("---")


def test_build_yaml_frontmatter_no_doc_title():
    note = MagicMock()
    note.tags = []
    note.created_at = datetime(2026, 1, 15, tzinfo=UTC)
    frontmatter = _build_yaml_frontmatter(note, ["Misc"], None)
    assert "source_document" not in frontmatter


# ---------------------------------------------------------------------------
# Integration tests via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_collection(client, name="Test Export", **kwargs):
    resp = client.post("/collections", json={"name": name, **kwargs})
    assert resp.status_code == 201
    return resp.json()


def _create_note(client, content="Note body text", tags=None):
    resp = client.post(
        "/notes",
        json={"content": content, "tags": tags or []},
    )
    assert resp.status_code == 201
    return resp.json()


def test_export_markdown_3_notes_returns_zip_with_3_files(client):
    col = _create_collection(client, name="Export Test Collection")
    note_ids = []
    for i in range(3):
        n = _create_note(client, content=f"# Note {i}\nBody of note {i}.")
        note_ids.append(n["id"])
    # Add notes to collection
    client.post(f"/collections/{col['id']}/notes", json={"note_ids": note_ids})

    resp = client.get(f"/collections/{col['id']}/export?format=markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "vault.zip" in resp.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert len(names) == 3
    # All files should be .md
    assert all(n.endswith(".md") for n in names)

    # Check frontmatter in first file
    content = zf.read(names[0]).decode()
    assert "---" in content
    assert "tags:" in content
    assert "collections:" in content


def test_export_markdown_wikilink_conversion(client):
    """[[note_id|text]] in note content should become [[target title]] in export."""
    col = _create_collection(client, name="Wikilink Export Collection")
    note_a = _create_note(client, content="# Target Note\nThis is the target.")
    note_b_id_short = note_a["id"]
    note_b = _create_note(
        client,
        content=f"# Source Note\nSee [[{note_b_id_short}|the target]] for details.",
    )
    client.post(
        f"/collections/{col['id']}/notes",
        json={"note_ids": [note_a["id"], note_b["id"]]},
    )

    resp = client.get(f"/collections/{col['id']}/export?format=markdown")
    assert resp.status_code == 200

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    all_content = "\n".join(zf.read(n).decode() for n in zf.namelist())
    # The [[id|text]] link should be converted to [[Target Note]]
    assert "[[Target Note]]" in all_content
    # The raw [[uuid|...]] form should not appear
    assert f"[[{note_b_id_short}|" not in all_content


def test_export_anki_returns_valid_apkg_bytes(client):
    """Anki .apkg is a zip internally; assert bytes parse as zip."""
    col = _create_collection(client, name="Anki Test Collection")
    # No flashcards needed -- empty apkg is still valid
    resp = client.get(f"/collections/{col['id']}/export?format=anki")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert ".apkg" in resp.headers.get("content-disposition", "")
    # apkg is a zip -- verify it parses
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert isinstance(zf.namelist(), list)


def test_export_anki_no_flashcards_returns_warning_header(client):
    col = _create_collection(client, name="Empty Deck Collection")
    resp = client.get(f"/collections/{col['id']}/export?format=anki")
    assert resp.status_code == 200
    assert "X-Luminary-Warning" in resp.headers
    assert "No flashcards" in resp.headers["X-Luminary-Warning"]


def test_export_empty_collection_markdown(client):
    col = _create_collection(client, name="Empty Markdown Collection")
    resp = client.get(f"/collections/{col['id']}/export?format=markdown")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.namelist() == []


def test_export_invalid_format_returns_422(client):
    col = _create_collection(client, name="Bad Format Collection")
    resp = client.get(f"/collections/{col['id']}/export?format=csv")
    assert resp.status_code == 422


def test_export_nonexistent_collection_returns_404(client):
    resp = client.get(f"/collections/{str(uuid.uuid4())}/export?format=markdown")
    assert resp.status_code == 404
