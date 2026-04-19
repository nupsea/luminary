"""Tests for S119 -- audio ingestion via faster-whisper.

All tests use a deterministic stub for AudioTranscriber to avoid loading the real
Whisper model (150MB+ download, CPU-heavy inference).
"""

import io
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel
from app.workflows.ingestion import IngestionState, _chunk_audio, _classify

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
# Pure function tests (no DB, no mocks needed)
# ---------------------------------------------------------------------------


def test_classify_returns_audio_for_mp3():
    assert _classify("", [], 0, "mp3") == "audio"


def test_classify_returns_audio_for_m4a():
    assert _classify("", [], 0, "m4a") == "audio"


def test_classify_returns_audio_for_wav():
    assert _classify("", [], 0, "wav") == "audio"


def test_chunk_audio_produces_start_end_metadata():
    segments = [
        {"start": 0.0, "end": 10.0, "text": "Hello world"},
        {"start": 10.0, "end": 20.0, "text": "This is a test"},
    ]
    doc_id = str(uuid.uuid4())
    chunks = _chunk_audio(segments, doc_id, window_seconds=60.0)
    assert len(chunks) >= 1
    for c in chunks:
        assert "start_time" in c
        assert "end_time" in c
        assert c["start_time"] >= 0.0
        assert c["end_time"] > c["start_time"]
        assert c["document_id"] == doc_id


def test_chunk_audio_window_boundary():
    """Segments spanning >60s are split into multiple chunks."""
    segments = [
        {"start": float(i * 10), "end": float(i * 10 + 10), "text": f"Segment {i}"}
        for i in range(10)  # 100 seconds total
    ]
    doc_id = str(uuid.uuid4())
    chunks = _chunk_audio(segments, doc_id, window_seconds=60.0)
    assert len(chunks) >= 2


def test_chunk_audio_empty_segments():
    chunks = _chunk_audio([], str(uuid.uuid4()))
    assert chunks == []


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_audio_allowed_extension_in_ingest_endpoint(test_db, monkeypatch):
    """POST /documents/ingest with .mp3 and content_type=audio returns HTTP 200."""

    async def _mock_run_ingestion(document_id, file_path, format, content_type=None):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("lecture.mp3", io.BytesIO(b"\x00" * 10), "audio/mpeg")},
            data={"content_type": "audio"},
        )
    assert resp.status_code == 200, resp.text
    assert "document_id" in resp.json()


async def test_transcribe_node_populates_parsed_document(test_db, tmp_path):
    """transcribe_node with a stubbed AudioTranscriber sets parsed_document + duration."""
    from app.workflows.ingestion import transcribe_node

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"\x00" * 100)

    class _MockAudioTranscriber:
        def transcribe(self, file_path: Path) -> tuple[list[dict], float]:
            return (
                [
                    {"start": 0.0, "end": 5.0, "text": "Hello"},
                    {"start": 5.0, "end": 10.0, "text": "World"},
                ],
                10.0,
            )

    doc_id = str(uuid.uuid4())
    engine, factory, _ = test_db
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="mp3",
                content_type="audio",
                word_count=0,
                page_count=0,
                file_path=str(audio_file),
                stage="parsing",
                tags=[],
            )
        )
        await session.commit()

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(audio_file),
        "format": "mp3",
        "parsed_document": None,
        "content_type": "audio",
        "chunks": None,
        "status": "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }

    # Patch at the source module where transcribe_node imports it
    with patch(
        "app.services.audio_transcriber.get_audio_transcriber",
        return_value=_MockAudioTranscriber(),
    ):
        result = await transcribe_node(state)

    assert result["status"] == "chunking", result.get("error")
    assert result["parsed_document"] is not None
    assert len(result["parsed_document"]["sections"]) >= 1
    assert result["audio_duration_seconds"] == 10.0
    assert "_audio_chunks" in result
    audio_chunks = result["_audio_chunks"]
    assert audio_chunks is not None
    assert all("start_time" in c and "end_time" in c for c in audio_chunks)
