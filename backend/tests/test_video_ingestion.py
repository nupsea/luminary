"""Tests for S121 -- video (MP4) ingestion via ffmpeg + faster-whisper.

Uses stubs for AudioTranscriber and mocks ffmpeg subprocess to avoid
real model downloads and system ffmpeg dependency.
"""

import io
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app  # noqa: F401 (used via ASGITransport)
from app.models import ChunkModel, DocumentModel
from app.workflows.ingestion import IngestionState, _classify, transcribe_node
from app.workflows.ingestion_nodes.chunk import chunk_node

# Shared DB fixture


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


# Pure function tests


def test_classify_returns_video_for_mp4():
    assert _classify("", [], 0, "mp4") == "video"


def test_classify_returns_audio_for_mp3_unchanged():
    """Existing audio classification still works after video extension added."""
    assert _classify("", [], 0, "mp3") == "audio"


def test_classify_returns_audio_for_wav_unchanged():
    assert _classify("", [], 0, "wav") == "audio"


# transcribe_node tests


async def test_transcribe_node_video_no_ffmpeg(test_db, tmp_path):
    """transcribe_node returns error state when ffmpeg is not found."""
    video_file = tmp_path / "lecture.mp4"
    video_file.write_bytes(b"\x00" * 100)

    doc_id = str(uuid.uuid4())
    engine, factory, _ = test_db
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="mp4",
                content_type="video",
                word_count=0,
                page_count=0,
                file_path=str(video_file),
                stage="parsing",
                tags=[],
            )
        )
        await session.commit()

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(video_file),
        "format": "mp4",
        "parsed_document": None,
        "content_type": "video",
        "chunks": None,
        "status": "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }

    with patch("app.workflows.ingestion_nodes.transcribe.resolve_tool", return_value=None):
        result = await transcribe_node(state)

    assert result["status"] == "error"
    assert result["error"] is not None
    assert "ffmpeg" in result["error"].lower()


async def test_transcribe_node_video_with_ffmpeg(test_db, tmp_path):
    """transcribe_node with ffmpeg + stubbed Whisper populates parsed_document."""
    video_file = tmp_path / "lecture.mp4"
    video_file.write_bytes(b"\x00" * 100)

    doc_id = str(uuid.uuid4())
    engine, factory, _ = test_db
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="mp4",
                content_type="video",
                word_count=0,
                page_count=0,
                file_path=str(video_file),
                stage="parsing",
                tags=[],
            )
        )
        await session.commit()

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(video_file),
        "format": "mp4",
        "parsed_document": None,
        "content_type": "video",
        "chunks": None,
        "status": "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }

    class _MockTranscriber:
        def transcribe(self, file_path: Path) -> tuple[list[dict], float]:
            return (
                [
                    {"start": 0.0, "end": 5.0, "text": "Hello from video"},
                    {"start": 5.0, "end": 10.0, "text": "This is a test"},
                ],
                10.0,
            )

    # Mock ffmpeg subprocess: returncode=0, proc completes successfully
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch(
            "app.workflows.ingestion_nodes.transcribe.resolve_tool",
            return_value="/usr/bin/ffmpeg",
        ),
        patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        ),
        patch(
            "app.services.audio_transcriber.get_audio_transcriber",
            return_value=_MockTranscriber(),
        ),
        patch("pathlib.Path.unlink"),  # skip actual file deletion
    ):
        result = await transcribe_node(state)

    assert result["status"] == "chunking", result.get("error")
    assert result["parsed_document"] is not None
    assert len(result["parsed_document"]["sections"]) >= 1
    assert result["audio_duration_seconds"] == 10.0
    assert result["_audio_chunks"] is not None
    assert len(result["_audio_chunks"]) >= 1


async def test_transcribe_node_passthrough_for_non_video(test_db, tmp_path):
    """transcribe_node is a no-op for non-audio/video content types."""
    doc_file = tmp_path / "book.txt"
    doc_file.write_text("Some text content")
    doc_id = str(uuid.uuid4())

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(doc_file),
        "format": "txt",
        "parsed_document": {
            "title": "Test",
            "sections": [],
            "raw_text": "text",
            "pages": 0,
            "word_count": 2,
            "format": "txt",
        },
        "content_type": "book",
        "chunks": None,
        "status": "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }

    result = await transcribe_node(state)
    # Should return state unchanged
    assert result["content_type"] == "book"
    assert result["status"] == "classifying"


# API endpoint tests


async def test_mp4_allowed_extension_in_ingest_endpoint(test_db, monkeypatch):
    """POST /documents/ingest with .mp4 and content_type=video returns HTTP 200."""

    async def _mock_run_ingestion(document_id, file_path, format, content_type=None):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("lecture.mp4", io.BytesIO(b"\x00" * 100), "video/mp4")},
            data={"content_type": "video"},
        )
    assert resp.status_code == 200, resp.text
    assert "document_id" in resp.json()


async def test_video_endpoint_returns_404_for_missing_doc(test_db):
    """GET /documents/{id}/video returns 404 for unknown document."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{uuid.uuid4()}/video")
    assert resp.status_code == 404


async def test_status_endpoint_returns_ffmpeg_error_message(test_db):
    """GET /documents/{id}/status propagates ffmpeg error_message when stage=error."""
    doc_id = str(uuid.uuid4())
    engine, factory, _ = test_db
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Video",
                format="mp4",
                content_type="video",
                word_count=0,
                page_count=0,
                file_path="/tmp/lecture.mp4",
                stage="error",
                error_message="ffmpeg is not installed. Install it with: brew install ffmpeg",
                tags=[],
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "error"
    assert "ffmpeg" in body["error_message"].lower()


async def test_video_endpoint_returns_400_for_non_video_doc(test_db, tmp_path, monkeypatch):
    """GET /documents/{id}/video returns 400 when document is not video type."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    doc_id = str(uuid.uuid4())
    txt_file = tmp_path / f"{doc_id}.txt"
    txt_file.write_text("hello")
    engine, factory, _ = test_db
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="txt",
                content_type="notes",
                word_count=1,
                page_count=0,
                file_path=str(txt_file),
                stage="complete",
                tags=[],
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/video")
    assert resp.status_code == 400


async def test_transcript_chunks_keep_the_moment_they_came_from(test_db):
    """A transcript chunk stores its window, so a citation can name a time.

    Transcription already knows both bounds -- `_chunk_audio` groups Whisper
    segments into ~60s windows carrying start_time/end_time -- and the write
    dropped them, so every `ChunkItem.start_time` the API served was null and a
    citation into a lecture could point at no moment in it.
    """
    doc_id = str(uuid.uuid4())
    _, factory, _ = test_db
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Lecture",
                format="mp3",
                content_type="audio",
                word_count=0,
                page_count=0,
                file_path="/tmp/lecture.mp3",
                stage="chunking",
                tags=[],
            )
        )
        await session.commit()

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": "/tmp/lecture.mp3",
        "format": "mp3",
        "parsed_document": None,
        "content_type": "audio",
        "chunks": None,
        "status": "chunking",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": 130.0,
        "_audio_chunks": [
            {"id": str(uuid.uuid4()), "document_id": doc_id, "text": "opening remarks",
             "index": 0, "start_time": 0.0, "end_time": 62.5},
            {"id": str(uuid.uuid4()), "document_id": doc_id, "text": "the main argument",
             "index": 1, "start_time": 62.5, "end_time": 130.0},
        ],
    }

    result = await chunk_node(state)
    assert result["status"] == "embedding", result.get("error")

    async with factory() as session:
        rows = (
            await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == doc_id)
                .order_by(ChunkModel.chunk_index)
            )
        ).scalars().all()
    assert [(r.start_time, r.end_time) for r in rows] == [(0.0, 62.5), (62.5, 130.0)]
