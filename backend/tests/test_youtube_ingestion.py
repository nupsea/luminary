"""Tests for S122 -- YouTube URL ingestion via yt-dlp.

Mocks yt-dlp subprocess calls to avoid requiring a live YouTube connection
or yt-dlp installation in CI.
"""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app  # noqa: F401 (used via ASGITransport)
from app.models import DocumentModel
from app.services.youtube_downloader import is_youtube_url

# ---------------------------------------------------------------------------
# Shared DB fixture
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


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_is_youtube_url_valid_watch():
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_is_youtube_url_valid_short():
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True


def test_is_youtube_url_invalid_vimeo():
    assert is_youtube_url("https://vimeo.com/123456") is False


def test_is_youtube_url_invalid_random():
    assert is_youtube_url("https://example.com/video.mp4") is False


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


async def test_ingest_url_returns_503_when_ytdlp_missing(test_db):
    """POST /documents/ingest-url returns 503 when yt-dlp is not on PATH."""
    with patch("app.services.youtube_downloader.shutil.which", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
    assert resp.status_code == 503
    assert "yt-dlp" in resp.json()["detail"].lower()


async def test_ingest_url_returns_503_when_ffmpeg_missing(test_db):
    """POST /documents/ingest-url returns 503 when ffmpeg is not on PATH."""
    with (
        patch("app.services.youtube_downloader.shutil.which", side_effect=lambda x: "/usr/bin/yt-dlp" if x == "yt-dlp" else None),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
    assert resp.status_code == 503
    assert "ffmpeg" in resp.json()["detail"].lower()


async def test_ingest_url_returns_400_for_non_youtube_url(test_db):
    """POST /documents/ingest-url returns 400 for non-YouTube URLs."""
    with patch("app.services.youtube_downloader.shutil.which", return_value="/usr/bin/yt-dlp"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://example.com/video.mp4"},
            )
    assert resp.status_code == 400


async def test_ingest_url_success_creates_document(test_db, monkeypatch):
    """POST /documents/ingest-url with valid YouTube URL creates a document row."""
    engine, factory, tmp_path = test_db

    async def _mock_run_ingestion(document_id, file_path, fmt, content_type=None):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)

    async def _fake_download_audio(url: str, dest_stem: Path) -> None:
        # Simulate yt-dlp writing the wav file to the expected location
        dest_stem.with_suffix(".wav").write_bytes(b"\x00" * 100)

    with (
        patch(
            "app.services.youtube_downloader.check_ytdlp_available",
            return_value=True,
        ),
        patch(
            "app.services.youtube_downloader.check_ffmpeg_available",
            return_value=True,
        ),
        patch(
            "app.services.youtube_downloader.fetch_metadata",
            new=AsyncMock(return_value={"title": "Test YouTube Video", "id": "abc123"}),
        ),
        patch(
            "app.services.youtube_downloader.download_audio",
            new=AsyncMock(side_effect=_fake_download_audio),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=abc123"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "document_id" in body
    doc_id = body["document_id"]

    # Verify DB row has source_url and video_title
    async with factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == doc_id)
        )
        doc = result.scalar_one_or_none()

    assert doc is not None
    assert doc.source_url == "https://www.youtube.com/watch?v=abc123"
    assert doc.video_title == "Test YouTube Video"
    assert doc.content_type == "audio"
    assert doc.format == "wav"


async def test_document_list_includes_source_url(test_db):
    """GET /documents returns source_url and video_title fields."""
    engine, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="My YouTube Talk",
                format="wav",
                content_type="audio",
                word_count=500,
                page_count=0,
                file_path="/tmp/test.wav",
                stage="complete",
                tags=[],
                source_url="https://www.youtube.com/watch?v=test123",
                video_title="My YouTube Talk",
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/documents")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    target = next((i for i in items if i["id"] == doc_id), None)
    assert target is not None
    assert target["source_url"] == "https://www.youtube.com/watch?v=test123"
    assert target["video_title"] == "My YouTube Talk"
