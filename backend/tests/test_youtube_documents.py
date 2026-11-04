"""A YouTube document already in the library: its fields and its transcript chunks, which the
reader and citations read. Importing one is the YouTube connector's (#434, #467)."""

import uuid

from httpx import ASGITransport, AsyncClient

from app.main import app  # noqa: F401 (used via ASGITransport)
from tests.factories import make_chunk, make_document


async def test_document_list_includes_source_url(test_db):
    """GET /documents returns source_url and video_title fields."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="My YouTube Talk",
                format="wav",
                form="dialogue",
                word_count=500,
                file_path="/tmp/test.wav",
                source_url="https://www.youtube.com/watch?v=test123",
                video_title="My YouTube Talk",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    target = next((i for i in items if i["id"] == doc_id), None)
    assert target is not None
    assert target["source_url"] == "https://www.youtube.com/watch?v=test123"
    assert target["video_title"] == "My YouTube Talk"


# S182: chunks endpoint and channel_name field tests


def test_document_model_has_youtube_url_and_channel_name():
    """DocumentModel includes youtube_url and channel_name nullable columns."""
    doc = make_document(
        id="test-id",
        title="Test",
        format="wav",
        form="dialogue",
        file_path="/tmp/test.wav",
        source_url="https://www.youtube.com/watch?v=abc",
        video_title="Test",
        channel_name="Test Channel",
        youtube_url="https://www.youtube.com/watch?v=abc",
    )
    assert doc.channel_name == "Test Channel"
    assert doc.youtube_url == "https://www.youtube.com/watch?v=abc"
    # Nullable: can be None
    doc2 = make_document(
        id="test-id-2",
        title="Test2",
        format="wav",
        form="dialogue",
        file_path="/tmp/test2.wav",
    )
    assert doc2.channel_name is None
    assert doc2.youtube_url is None


async def test_get_document_chunks_returns_youtube_chunks(test_db):
    """GET /documents/{id}/chunks returns chunks for a YouTube document."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="YouTube Lecture",
                format="wav",
                form="dialogue",
                word_count=300,
                file_path="/tmp/lecture.wav",
                source_url="https://www.youtube.com/watch?v=xyz",
                video_title="YouTube Lecture",
                channel_name="Lecture Channel",
            )
        )

        for i in range(3):
            session.add(
                make_chunk(
                    document_id=doc_id,
                    text=f"Transcript chunk {i} text.",
                    chunk_index=i,
                    token_count=10,
                )
            )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/chunks")

    assert resp.status_code == 200
    chunks = resp.json()
    assert len(chunks) == 3
    # Returned in chunk_index order
    assert chunks[0]["chunk_index"] == 0
    assert chunks[1]["chunk_index"] == 1
    assert chunks[2]["chunk_index"] == 2
    assert "text" in chunks[0]
    assert "Transcript chunk 0 text." in chunks[0]["text"]


async def test_get_document_chunks_returns_404_for_missing_document(test_db):
    """GET /documents/{id}/chunks returns 404 when document does not exist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/nonexistent-doc-id/chunks")

    assert resp.status_code == 404


async def test_get_document_chunks_returns_empty_for_no_chunks(test_db):
    """GET /documents/{id}/chunks returns [] when document has no chunks yet."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="Processing Video",
                format="wav",
                form="dialogue",
                file_path="/tmp/processing.wav",
                stage="parsing",
                source_url="https://www.youtube.com/watch?v=new",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/chunks")

    assert resp.status_code == 200
    assert resp.json() == []
