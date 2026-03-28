"""Tests for tag storage, retrieval, and filtering (S62 and S162)."""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _make_doc(doc_id: str | None = None, **kwargs) -> DocumentModel:
    defaults = {
        "id": doc_id or str(uuid.uuid4()),
        "title": "Test Doc",
        "format": "txt",
        "content_type": "notes",
        "word_count": 100,
        "page_count": 1,
        "file_path": "/tmp/test.txt",
        "stage": "complete",
        "tags": [],
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_patch_tags_stores_list(test_db):
    """PATCH /documents/{id}/tags stores tags as a JSON list; GET returns list[str]."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, tags=[]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        patch_resp = await client.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["physics", "science"]},
        )
        assert patch_resp.status_code == 200
        body = patch_resp.json()
        assert isinstance(body["tags"], list)
        assert body["tags"] == ["physics", "science"]

        # GET /documents and verify tags appear as list[str]
        list_resp = await client.get("/documents")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        match = next((i for i in items if i["id"] == doc_id), None)
        assert match is not None
        assert isinstance(match["tags"], list)
        assert match["tags"] == ["physics", "science"]


@pytest.mark.anyio
async def test_tag_filter_returns_matching_docs(test_db):
    """GET /documents?tag=X returns only documents whose tag list includes X."""
    engine, factory, _ = test_db
    doc_physics = str(uuid.uuid4())
    doc_history = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_physics, title="Physics Book", tags=["physics"]))
        session.add(_make_doc(doc_history, title="History Book", tags=["history"]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/documents?tag=physics")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = [i["id"] for i in items]
        assert doc_physics in ids
        assert doc_history not in ids


@pytest.mark.anyio
async def test_tag_filter_no_substring_collision(test_db):
    """GET /documents?tag=bio must NOT match a doc tagged 'biology' (exact element only)."""
    engine, factory, _ = test_db
    doc_bio = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_bio, title="Biology Book", tags=["biology"]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/documents?tag=bio")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = [i["id"] for i in items]
        # 'bio' is a substring of 'biology' but must NOT match as an element
        assert doc_bio not in ids


@pytest.mark.anyio
async def test_patch_tags_replaces_not_appends(test_db):
    """Second PATCH replaces the tag list entirely, not appends."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id, tags=["old-tag"]))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # First patch
        await client.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["first"]},
        )
        # Second patch replaces
        patch2 = await client.patch(
            f"/documents/{doc_id}/tags",
            json={"tags": ["second"]},
        )
        assert patch2.status_code == 200
        assert patch2.json()["tags"] == ["second"]

        # Verify via GET /documents
        list_resp = await client.get("/documents")
        match = next((i for i in list_resp.json()["items"] if i["id"] == doc_id), None)
        assert match is not None
        assert match["tags"] == ["second"]
        assert "first" not in match["tags"]
        assert "old-tag" not in match["tags"]


# ===========================================================================
# S162: Hierarchical note tags -- NoteTagIndexModel, CanonicalTagModel, prefix API
# ===========================================================================


@pytest.fixture()
def notes_client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# NoteTagIndexModel population on note create
# ---------------------------------------------------------------------------


def test_s162_create_note_populates_tag_index(notes_client):
    """Note with hierarchical tags creates NoteTagIndexModel rows; prefix filter works."""
    resp = notes_client.post(
        "/notes",
        json={"content": "Python and Go notes", "tags": ["programming/python", "programming/go"]},
    )
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    # Both child tags must appear in exact filter
    py_resp = notes_client.get("/notes?tag=programming/python")
    assert any(n["id"] == note_id for n in py_resp.json())

    go_resp = notes_client.get("/notes?tag=programming/go")
    assert any(n["id"] == note_id for n in go_resp.json())


# ---------------------------------------------------------------------------
# Hierarchical prefix filtering
# ---------------------------------------------------------------------------


def test_s162_parent_tag_filter_returns_children(notes_client):
    """GET /notes?tag=programming returns notes tagged 'programming/python' and 'programming/go'."""
    unique = uuid.uuid4().hex[:8]
    note_python = notes_client.post(
        "/notes",
        json={"content": f"Python note {unique}", "tags": [f"prog{unique}/python"]},
    ).json()
    note_go = notes_client.post(
        "/notes",
        json={"content": f"Go note {unique}", "tags": [f"prog{unique}/go"]},
    ).json()
    unrelated = notes_client.post(
        "/notes",
        json={"content": f"Unrelated {unique}", "tags": [f"biology{unique}"]},
    ).json()

    resp = notes_client.get(f"/notes?tag=prog{unique}")
    assert resp.status_code == 200
    result_ids = {n["id"] for n in resp.json()}

    assert note_python["id"] in result_ids
    assert note_go["id"] in result_ids
    assert unrelated["id"] not in result_ids


# ---------------------------------------------------------------------------
# Deletion removes index rows and decrements note_count
# ---------------------------------------------------------------------------


def test_s162_delete_note_removes_tag_rows_and_decrements_count(notes_client):
    """Deleting a note removes its NoteTagIndexModel rows; canonical tag note_count goes to 0."""
    unique_tag = f"del-tag-{uuid.uuid4().hex[:8]}"
    resp = notes_client.post(
        "/notes",
        json={"content": "Note to delete", "tags": [unique_tag]},
    )
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    # Canonical tag should exist with count=1
    ac_resp = notes_client.get(f"/tags/autocomplete?q={unique_tag}")
    matching = [t for t in ac_resp.json() if t["id"] == unique_tag]
    assert len(matching) == 1
    assert matching[0]["note_count"] == 1

    # Delete the note
    assert notes_client.delete(f"/notes/{note_id}").status_code == 204

    # Count decremented to 0
    ac_resp2 = notes_client.get(f"/tags/autocomplete?q={unique_tag}")
    matching2 = [t for t in ac_resp2.json() if t["id"] == unique_tag]
    if matching2:
        assert matching2[0]["note_count"] == 0

    # Note no longer in tag filter
    filter_resp = notes_client.get(f"/notes?tag={unique_tag}")
    assert all(n["id"] != note_id for n in filter_resp.json())


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------


def test_s162_autocomplete_prefix_matches(notes_client):
    """Autocomplete returns tags matching the prefix query."""
    unique = uuid.uuid4().hex[:6]
    notes_client.post("/notes", json={"content": "Note A", "tags": [f"auto{unique}"]})
    notes_client.post("/notes", json={"content": "Note B", "tags": [f"auto{unique}/child"]})

    resp = notes_client.get(f"/tags/autocomplete?q=auto{unique}")
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert f"auto{unique}" in ids or f"auto{unique}/child" in ids


def test_s162_autocomplete_limit_10(notes_client):
    """Autocomplete returns at most 10 results."""
    unique = uuid.uuid4().hex[:4]
    for i in range(15):
        notes_client.post("/notes", json={"content": f"Bulk {i}", "tags": [f"bulk{unique}{i:02d}"]})

    resp = notes_client.get(f"/tags/autocomplete?q=bulk{unique}")
    assert resp.status_code == 200
    assert len(resp.json()) <= 10


# ---------------------------------------------------------------------------
# GET /tags/tree
# ---------------------------------------------------------------------------


def test_s162_tag_tree_nests_children(notes_client):
    """GET /tags/tree nests children under parents with correct structure."""
    unique = uuid.uuid4().hex[:6]
    parent_tag = f"{unique}root"
    child_tag = f"{unique}root/{unique}sub"

    notes_client.post("/notes", json={"content": "Root note", "tags": [parent_tag]})
    notes_client.post("/notes", json={"content": "Child note", "tags": [child_tag]})

    resp = notes_client.get("/tags/tree")
    assert resp.status_code == 200
    tree = resp.json()

    parent_node = next((t for t in tree if t["id"] == parent_tag), None)
    assert parent_node is not None, f"Parent tag '{parent_tag}' not found in tree"
    child_ids = [c["id"] for c in parent_node["children"]]
    assert child_tag in child_ids


def test_s162_tag_tree_inclusive_count(notes_client):
    """Parent node note_count includes own notes plus descendant notes."""
    unique = uuid.uuid4().hex[:6]
    parent_tag = f"{unique}inc"
    child_tag = f"{unique}inc/{unique}child"

    notes_client.post("/notes", json={"content": "Parent note", "tags": [parent_tag]})
    notes_client.post("/notes", json={"content": "Child 1", "tags": [child_tag]})
    notes_client.post("/notes", json={"content": "Child 2", "tags": [child_tag]})

    resp = notes_client.get("/tags/tree")
    tree = resp.json()
    parent_node = next((t for t in tree if t["id"] == parent_tag), None)
    assert parent_node is not None
    assert parent_node["note_count"] == 3  # 1 direct + 2 children


# ---------------------------------------------------------------------------
# DELETE /tags/{id}
# ---------------------------------------------------------------------------


def test_s162_delete_tag_409_when_notes_exist(notes_client):
    """DELETE /tags/{id} returns 409 when tag note_count > 0."""
    unique_tag = f"protected-{uuid.uuid4().hex[:8]}"
    notes_client.post("/notes", json={"content": "Note", "tags": [unique_tag]})

    resp = notes_client.delete(f"/tags/{unique_tag}")
    assert resp.status_code == 409


def test_s162_delete_tag_204_when_empty(notes_client):
    """DELETE /tags/{id} succeeds (204) when tag has no notes."""
    unique_tag = f"empty-tag-{uuid.uuid4().hex[:8]}"
    create_resp = notes_client.post(
        "/tags",
        json={"id": unique_tag, "display_name": "Empty"},
    )
    assert create_resp.status_code == 201

    assert notes_client.delete(f"/tags/{unique_tag}").status_code == 204


# ---------------------------------------------------------------------------
# Concurrent note creates do not corrupt note_count
# ---------------------------------------------------------------------------


async def test_s162_concurrent_creates_note_count_accurate(test_db):
    """5 concurrent POST /notes with same tag must result in note_count=5 (SQLite atomic UPDATE).

    Uses test_db fixture so tables are initialized in the isolated in-memory DB.
    asyncio.gather fires 5 simultaneous POST /notes requests; the ON CONFLICT atomic
    UPDATE in _sync_tag_index must prevent count corruption.
    """
    unique_tag = f"concurrent-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await asyncio.gather(
            *[
                client.post(
                    "/notes",
                    json={"content": f"Note {i}", "tags": [unique_tag]},
                )
                for i in range(5)
            ]
        )
        resp = await client.get(f"/tags/autocomplete?q={unique_tag}")
        results = resp.json()
        matching = [t for t in results if t["id"] == unique_tag]
        assert len(matching) == 1
        assert matching[0]["note_count"] == 5


# ===========================================================================
# S165: POST /tags/merge -- atomic tag merge
# ===========================================================================


@pytest.mark.flaky(retries=3)
async def test_s165_merge_replaces_source_tag_in_notes():
    """POST /tags/merge replaces source tag with target in all affected notes."""
    src_tag = f"old-tag-{id(object()):x}"
    tgt_tag = f"new-tag-{id(object()):x}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create two notes with src_tag
        n1 = await client.post("/notes", json={"content": "Note 1", "tags": [src_tag]})
        n2 = await client.post("/notes", json={"content": "Note 2", "tags": [src_tag, tgt_tag]})
        assert n1.status_code == 201
        assert n2.status_code == 201
        n1_id = n1.json()["id"]
        n2_id = n2.json()["id"]

        # Create target canonical tag (source is auto-created by note POST)
        await client.post("/tags", json={"id": tgt_tag, "display_name": "new-tag"})

        resp = await client.post(
            "/tags/merge",
            json={"source_tag_id": src_tag, "target_tag_id": tgt_tag},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["affected_notes"] == 2

        # Verify source tag is gone from both notes
        g1 = await client.get(f"/notes/{n1_id}")
        g2 = await client.get(f"/notes/{n2_id}")
        assert g1.status_code == 200
        assert g2.status_code == 200
        assert src_tag not in g1.json()["tags"]
        assert tgt_tag in g1.json()["tags"]
        # n2 had both tags; after merge it should have target only (deduplicated)
        assert src_tag not in g2.json()["tags"]
        assert g2.json()["tags"].count(tgt_tag) == 1


async def test_s165_merge_creates_alias_and_deletes_source():
    """POST /tags/merge creates TagAliasModel row and removes source CanonicalTagModel."""
    src_tag = f"source-alias-{id(object()):x}"
    tgt_tag = f"target-alias-{id(object()):x}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/notes", json={"content": "Note", "tags": [src_tag]})
        await client.post("/tags", json={"id": tgt_tag, "display_name": "target-alias"})

        resp = await client.post(
            "/tags/merge",
            json={"source_tag_id": src_tag, "target_tag_id": tgt_tag},
        )
        assert resp.status_code == 200

        # Source tag must no longer exist in canonical list
        list_resp = await client.get("/tags")
        tag_ids = [t["id"] for t in list_resp.json()]
        assert src_tag not in tag_ids
        assert tgt_tag in tag_ids


async def test_s165_merge_404_unknown_source():
    """POST /tags/merge returns 404 when source tag does not exist."""
    tgt_tag = f"target-{id(object()):x}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/tags", json={"id": tgt_tag, "display_name": "target"})

        resp = await client.post(
            "/tags/merge",
            json={"source_tag_id": "no-such-tag-xyz", "target_tag_id": tgt_tag},
        )
        assert resp.status_code == 404


async def test_s165_merge_422_same_source_and_target():
    """POST /tags/merge returns 422 when source == target."""
    tag = f"self-merge-{id(object()):x}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/notes", json={"content": "Note", "tags": [tag]})

        resp = await client.post(
            "/tags/merge",
            json={"source_tag_id": tag, "target_tag_id": tag},
        )
        assert resp.status_code == 422
