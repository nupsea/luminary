"""Tests for S192: auto-collection per document.

Covers:
- GET /collections/by-document/{document_id} returns auto-collection or 404
- POST /collections/auto/{document_id} creates auto-collection; idempotent
- NoteCollectionModel.auto_document_id column present
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_document(client, title="Test Book", content_type="book") -> str:
    """Create a minimal document and return its id."""
    doc_id = str(uuid.uuid4())
    import asyncio  # noqa: PLC0415

    from app.database import get_session_factory  # noqa: PLC0415
    from app.models import DocumentModel  # noqa: PLC0415

    async def _insert():
        async with get_session_factory()() as session:
            doc = DocumentModel(
                id=doc_id,
                title=title,
                format="txt",
                content_type=content_type,
                word_count=1000,
                page_count=10,
                file_path="/tmp/fake.txt",
                stage="complete",
            )
            session.add(doc)
            await session.commit()

    asyncio.run(_insert())
    return doc_id


# ---------------------------------------------------------------------------
# GET /collections/by-document/{document_id}
# ---------------------------------------------------------------------------


def test_by_document_404_when_no_auto_collection(client):
    """GET /collections/by-document returns 404 for a doc with no auto-collection."""
    resp = client.get(f"/collections/by-document/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_by_document_returns_auto_collection(client):
    """GET /collections/by-document returns the auto-collection after creation."""
    doc_id = _create_document(client)
    # Create auto-collection first
    create_resp = client.post(f"/collections/auto/{doc_id}")
    assert create_resp.status_code == 201
    col_data = create_resp.json()

    # Now GET should find it
    resp = client.get(f"/collections/by-document/{doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == col_data["id"]
    assert data["auto_document_id"] == doc_id


# ---------------------------------------------------------------------------
# POST /collections/auto/{document_id}
# ---------------------------------------------------------------------------


def test_create_auto_collection(client):
    """POST /collections/auto creates auto-collection with correct name and color."""
    doc_id = _create_document(client, title="The Odyssey", content_type="book")
    resp = client.post(f"/collections/auto/{doc_id}")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "The Odyssey Notes"
    assert data["auto_document_id"] == doc_id
    assert data["color"] == "#8B5CF6"  # book color


def test_create_auto_collection_idempotent(client):
    """POST /collections/auto returns same collection on second call."""
    doc_id = _create_document(client)
    resp1 = client.post(f"/collections/auto/{doc_id}")
    assert resp1.status_code == 201
    resp2 = client.post(f"/collections/auto/{doc_id}")
    # Idempotent -- returns existing (still 201 since the endpoint always returns 201)
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]


def test_create_auto_collection_404_for_missing_document(client):
    """POST /collections/auto returns 404 when document does not exist."""
    resp = client.post(f"/collections/auto/{uuid.uuid4()}")
    assert resp.status_code == 404
