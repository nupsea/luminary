"""A YouTube link through a connector reads as it does through the built-in download (#434)."""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import DocumentModel
from app.services import connectors
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.transcript_vocabulary import hotwords, vocabulary_from_metadata
from tests.connector_fixture import AUDIO, TALK, install

URL = "https://www.youtube.com/watch?v=t1"
FFMPEG = "/opt/fixture/bin/ffmpeg"


@pytest.fixture(scope="module")
def video_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("connectors")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(connectors, "connectors_root", lambda: root)
        install(tmp_path_factory, root, "fixture-video", "FixtureVideo")
        yield root


@pytest.fixture(autouse=True)
def _media_installed(monkeypatch):
    from app.services import python_extras

    monkeypatch.setitem(python_extras.EXTRA_WEIGHTS, "transcription", (lambda: True, lambda: None))
    monkeypatch.setattr(
        "app.services.connectors.resolve_tool", lambda name: FFMPEG if name == "ffmpeg" else None
    )


class _Transcriber:
    def __init__(self) -> None:
        self.hotwords: list[str | None] = []

    def is_whole_word(self, word: str) -> bool:
        return True

    def transcribe(self, file_path: Path, *, hotwords=None, on_progress=None):
        self.hotwords.append(hotwords)
        return [{"start": 2.0, "end": 6.0, "text": "we store vectors in lance db"}], 70.0


async def _transcribe(doc: DocumentModel) -> tuple[list[tuple], list[str | None]]:
    from app.workflows.ingestion import transcribe_node

    transcriber = _Transcriber()
    quiet = AsyncMock(return_value=None)
    with (
        patch("app.services.audio_transcriber.get_audio_transcriber", return_value=transcriber),
        patch("app.workflows.ingestion_nodes.transcribe.detect_technical_transcript", new=quiet),
        patch("app.workflows.ingestion_nodes.transcribe.detect_register", new=quiet),
    ):
        state = await transcribe_node(
            {
                "document_id": doc.id,
                "file_path": doc.file_path,
                "format": doc.format,
                "parsed_document": None,
                "form": "dialogue",
                "chunks": None,
                "status": "classifying",
                "error": None,
                "section_summary_count": None,
                "audio_duration_seconds": None,
                "_audio_chunks": None,
            }  # fmt: skip
        )
    assert state["status"] == "chunking", state.get("error")
    chunks = [(c["start_time"], c["end_time"], c["text"]) for c in state["_audio_chunks"]]
    return chunks, transcriber.hotwords


async def _post(url: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/documents/ingest-url", json={"url": url})
        if resp.status_code == 200:
            await get_ingestion_jobs().get(resp.json()["document_id"])
    return resp


async def _through_connector(url: str, factory) -> DocumentModel:
    ingested = AsyncMock()
    with patch("app.workflows.connector_ingestion.run_ingestion", new=ingested):
        resp = await _post(url)
    assert resp.status_code == 200, resp.text
    async with factory() as session:
        doc = await session.get(DocumentModel, resp.json()["document_id"])
    assert doc.stage != "error", doc.error_message
    ingested.assert_awaited_once_with(doc.id, doc.file_path, doc.format)
    return doc


# What the built-in download produced for this talk before #467 removed it (#434 compared
# the two directly): yt-dlp's metadata through the same vocabulary rule, and the cue times.
_CUES = [(1.0, 3.5, "We store vectors in LanceDB"), (65.25, 67.0, "R&D on Kimi K3")]
_SPEECH = [(2.0, 6.0, "we store vectors in lance db")]


@pytest.mark.parametrize("captions", [True, False], ids=["captions", "speech"])
async def test_a_youtube_link_reads_through_the_connector_as_the_download_did(
    test_db, video_root, monkeypatch, captions
):
    _, factory, tmp_path = test_db
    url = URL if captions else f"{URL}&nocaps"
    via_connector = await _through_connector(url, factory)

    vocabulary = vocabulary_from_metadata(TALK)
    assert (
        via_connector.format, via_connector.title, via_connector.video_title,
        via_connector.channel_name, via_connector.youtube_url, via_connector.source_url,
        via_connector.transcript_vocabulary,
    ) == ("flac", TALK["title"], TALK["title"], TALK["uploader"], url, url, vocabulary)  # fmt: skip
    assert vocabulary[:2] == [TALK["title"], TALK["uploader"]]
    stored = tmp_path / "raw" / f"{via_connector.id}.bundle"
    assert Path(via_connector.file_path).parent == stored / "assets"
    # Transcript, timestamps (where a citation seeks the player) and Whisper's priming.
    chunks, primed = await _transcribe(via_connector)
    if captions:
        assert (chunks, primed) == (_CUES, [])
    else:
        assert (chunks, primed) == (_SPEECH, [hotwords(vocabulary)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        played = await client.get(f"/documents/{via_connector.id}/audio")
    assert (played.status_code, played.content) == (200, AUDIO)


async def test_reimport_reads_the_stored_bundle_with_the_network_refused(
    test_db, video_root, monkeypatch
):
    _, factory, _ = test_db
    doc = await _through_connector(URL, factory)
    expected = await _transcribe(doc)

    def _refuse(*_args, **_kwargs):
        raise OSError("network refused by the test")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    fetch = AsyncMock(side_effect=AssertionError("re-import ran the connector"))
    monkeypatch.setattr("app.workflows.connector_ingestion.call", fetch)
    reingested = AsyncMock()
    monkeypatch.setattr("app.routers.documents.run_ingestion", reingested)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/documents/{doc.id}/reparse", json={"confirm": True})
        await get_ingestion_jobs().get(doc.id)

    assert resp.json()["source"] == "file", resp.text
    reingested.assert_called_once_with(doc.id, doc.file_path, "flac")
    assert await _transcribe(doc) == expected
    fetch.assert_not_called()


@pytest.mark.parametrize(
    ("ffmpeg", "transcriber", "missing"),
    [(None, True, ["ffmpeg"]), (FFMPEG, False, ["transcription"])],
    ids=["ffmpeg", "transcriber"],
)
async def test_a_claimed_link_is_refused_before_fetching_what_it_cannot_ingest(
    test_db, video_root, monkeypatch, ffmpeg, transcriber, missing
):
    _, factory, _ = test_db
    from app.services import python_extras

    monkeypatch.setattr("app.services.connectors.resolve_tool", lambda name: ffmpeg)
    if not transcriber:
        monkeypatch.setitem(
            python_extras.EXTRA_WEIGHTS, "transcription", (lambda: False, lambda: None)
        )
    fetch = AsyncMock()
    monkeypatch.setattr("app.workflows.connector_ingestion.call", fetch)

    resp = await _post(URL)

    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert detail["missing"] == missing
    assert detail["message"].startswith("Fixture Video needs")
    fetch.assert_not_called()
    async with factory() as session:
        assert await session.scalar(DocumentModel.__table__.select().limit(1)) is None
