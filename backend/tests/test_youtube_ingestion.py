"""Tests for S122 -- YouTube URL ingestion via yt-dlp.

Mocks yt-dlp subprocess calls to avoid requiring a live YouTube connection
or yt-dlp installation in CI.
"""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app  # noqa: F401 (used via ASGITransport)
from app.models import DocumentModel
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.youtube_downloader import is_youtube_url
from tests.factories import make_chunk, make_document


@pytest.fixture(autouse=True)
def _transcription_installed(monkeypatch):
    """Pin Speech to text as installed, weights included, so these tests exercise
    yt-dlp and ffmpeg rather than whatever this machine has downloaded."""
    from app.services import python_extras

    monkeypatch.setitem(python_extras.EXTRA_WEIGHTS, "transcription", (lambda: True, lambda: None))


class _FakeYtDlp:
    """A yt-dlp process: `stdout` lines, then exit; or, with `hang`, never exits."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, hang=False):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        if not hang:
            self.stdout.feed_eof()
            self.stderr.feed_eof()
        self._exit = returncode
        self.returncode = None
        self.killed = False

    async def wait(self):
        self.returncode = self._exit
        return self.returncode

    def kill(self):
        self.killed = True


# Shared DB fixture


# Pure function tests


def test_is_youtube_url_valid_watch():
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_is_youtube_url_valid_short():
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True


def test_is_youtube_url_invalid_vimeo():
    assert is_youtube_url("https://vimeo.com/123456") is False


def test_is_youtube_url_invalid_random():
    assert is_youtube_url("https://example.com/video.mp4") is False


# API endpoint tests


async def test_ingest_url_returns_503_when_ytdlp_missing(test_db):
    """POST /documents/ingest-url returns 503 when yt-dlp is not installed."""
    with patch("app.services.youtube_downloader.resolve_tool", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
    assert resp.status_code == 503
    # `detail` is a dict now, not a sentence: the client needs component ids so
    # it can offer the in-app install rather than printing shell instructions.
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["missing"], "the error must name what is missing"
    # yt-dlp has no catalogue entry, so there is nothing to install in-app and
    # no button may be offered for it. `components` used to carry it anyway,
    # because an unknown id defaulted to installable.
    assert detail["components"] == []


async def test_ingest_url_returns_503_when_ffmpeg_missing(test_db):
    """POST /documents/ingest-url returns 503 when ffmpeg is not installed."""

    async def _ffmpeg_missing():
        return {"youtube_ingest": {"available": False, "requires": ["ffmpeg"]}}

    # ffmpeg pinned absent rather than inherited from the machine: the direct
    # check decides for tools it can run, so this must not depend on whether the
    # developer happens to have ffmpeg installed.
    with (
        patch("app.routers.documents.capabilities", _ffmpeg_missing),
        patch("app.services.youtube_downloader.check_ffmpeg_available", return_value=False),
        patch("app.services.youtube_downloader.check_ytdlp_available", return_value=True),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    # ffmpeg has no automated installer, so it is named in the message but is
    # not offered as a button that would fail on click.
    assert detail["components"] == []
    assert "Audio and video support" in detail["message"]


async def test_ingest_url_returns_400_for_non_youtube_url(test_db):
    """POST /documents/ingest-url returns 400 for non-YouTube URLs."""
    with patch("app.services.youtube_downloader.resolve_tool", return_value="/usr/bin/yt-dlp"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://example.com/video.mp4"},
            )
    assert resp.status_code == 400


async def test_ingest_url_success_creates_document(test_db, monkeypatch):
    """POST /documents/ingest-url with valid YouTube URL creates a document row."""
    engine, factory, tmp_path = test_db

    async def _mock_run_ingestion(document_id, file_path, fmt, content_type=None, **_kwargs):
        pass

    monkeypatch.setattr("app.workflows.youtube_ingestion.run_ingestion", _mock_run_ingestion)

    async def _fake_download_audio(url: str, dest_stem: Path, on_progress=None) -> None:
        # Simulate yt-dlp writing the wav file to the expected location
        dest_stem.with_suffix(".flac").write_bytes(b"\x00" * 100)

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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=abc123"},
            )
        await get_ingestion_jobs().get(resp.json()["document_id"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "document_id" in body
    doc_id = body["document_id"]

    # Verify DB row has source_url and video_title
    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = result.scalar_one_or_none()

    assert doc is not None
    assert doc.source_url == "https://www.youtube.com/watch?v=abc123"
    assert doc.video_title == "Test YouTube Video"
    assert doc.format == "flac"


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


async def test_ingest_url_stores_channel_name(test_db, monkeypatch):
    """POST /documents/ingest-url stores channel_name from yt-dlp metadata."""
    engine, factory, tmp_path = test_db

    async def _mock_run_ingestion(document_id, file_path, fmt, content_type=None, **_kwargs):
        pass

    monkeypatch.setattr("app.workflows.youtube_ingestion.run_ingestion", _mock_run_ingestion)

    async def _fake_download_audio(url: str, dest_stem: Path, on_progress=None) -> None:
        dest_stem.with_suffix(".flac").write_bytes(b"\x00" * 100)

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
            new=AsyncMock(
                return_value={
                    "title": "My Lecture",
                    "uploader": "Prof. Smith",
                    "id": "lec001",
                }
            ),
        ),
        patch(
            "app.services.youtube_downloader.download_audio",
            new=AsyncMock(side_effect=_fake_download_audio),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://www.youtube.com/watch?v=lec001"},
            )
        await get_ingestion_jobs().get(resp.json()["document_id"])

    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]

    from sqlalchemy import select as sa_select

    async with factory() as session:
        result = await session.execute(sa_select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = result.scalar_one_or_none()

    assert doc is not None
    assert doc.channel_name == "Prof. Smith"
    assert doc.youtube_url == "https://www.youtube.com/watch?v=lec001"


async def test_download_passes_the_resolved_ffmpeg_location(monkeypatch, tmp_path):
    """yt-dlp inherits the bundle's PATH, not wherever we found ffmpeg.

    Luminary's own capability check passed while the download still died on
    "ffprobe and ffmpeg not found", because resolving the binary for ourselves
    does nothing for the subprocess. The directory is passed, not the binary:
    postprocessing needs ffprobe too and it sits beside ffmpeg.
    """
    import app.services.youtube_downloader as yt

    captured: list[str] = []

    async def _fake_exec(*args, **kwargs):
        captured.extend(args)
        return _FakeYtDlp()

    # Built through Path rather than hardcoded, so the expected separator
    # matches whatever the code under test normalizes to on this platform --
    # the mac-style prefix is arbitrary, the code's job is a real OS path.
    monkeypatch.setattr(yt, "resolve_tool", lambda name: str(Path("/opt/homebrew/bin") / name))
    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)

    await yt.download_audio("https://youtu.be/x", tmp_path / "out")

    assert "--ffmpeg-location" in captured
    assert captured[captured.index("--ffmpeg-location") + 1] == str(Path("/opt/homebrew/bin"))


async def test_download_omits_the_flag_when_ffmpeg_is_not_found(monkeypatch, tmp_path):
    """An empty --ffmpeg-location is worse than none: yt-dlp would take it."""
    import app.services.youtube_downloader as yt

    captured: list[str] = []

    async def _fake_exec(*args, **kwargs):
        captured.extend(args)
        return _FakeYtDlp()

    monkeypatch.setattr(yt, "resolve_tool", lambda name: None)
    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)

    await yt.download_audio("https://youtu.be/x", tmp_path / "out")

    assert "--ffmpeg-location" not in captured


async def test_metadata_failure_names_yt_dlps_reason(monkeypatch):
    """The exit code alone left the user nothing to act on; yt-dlp's ERROR line does."""
    import app.services.youtube_downloader as yt

    class _Proc:
        returncode = 1

        async def communicate(self):
            return b"", (
                b"WARNING: [youtube] x: HTTP Error 429: Too Many Requests\n"
                b"ERROR: [youtube] x: Sign in to confirm you\xe2\x80\x99re not a bot.\n"
            )

    async def _fake_exec(*args, **kwargs):
        return _Proc()

    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(RuntimeError, match="not a bot"):
        await yt.fetch_metadata("https://youtu.be/x")


def _youtube_ready(download_audio):
    """yt-dlp and ffmpeg present, metadata answered, `download_audio` standing in."""
    from contextlib import ExitStack

    stack = ExitStack()
    for target, kwargs in (
        ("check_ytdlp_available", {"return_value": True}),
        ("check_ffmpeg_available", {"return_value": True}),
        ("fetch_metadata", {"new": AsyncMock(return_value={"title": "Talk", "id": "t1"})}),
        ("download_audio", {"new": download_audio}),
    ):
        stack.enter_context(patch(f"app.services.youtube_downloader.{target}", **kwargs))
    return stack


async def test_ingest_url_returns_before_the_download_finishes(test_db, monkeypatch):
    """The download used to run inside the request, so no document existed to report on
    until the whole talk was down. It is the job's first stage now, and it reports."""
    _, factory, _ = test_db
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.youtube_ingestion.run_ingestion", ingested)
    halfway = asyncio.Event()
    release = asyncio.Event()

    async def _slow_download(url, dest_stem, on_progress=None):
        on_progress(0.5)
        halfway.set()
        await release.wait()
        dest_stem.with_suffix(".flac").write_bytes(b"\x00" * 100)

    with _youtube_ready(_slow_download):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url", json={"url": "https://www.youtube.com/watch?v=t1"}
            )
            assert resp.status_code == 200, resp.text
            doc_id = resp.json()["document_id"]
            await asyncio.wait_for(halfway.wait(), timeout=5)
            status = (await client.get(f"/documents/{doc_id}/status")).json()

            assert status["stage"] == "downloading"
            assert status["stage_pct"] == 50
            assert status["progress_pct"] == 6  # halfway from 2 to 10
            ingested.assert_not_called()

            release.set()
            await get_ingestion_jobs().get(doc_id)
            after = (await client.get(f"/documents/{doc_id}/status")).json()

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    ingested.assert_awaited_once()
    assert ingested.call_args.args[:3] == (doc_id, doc.file_path, "flac")
    assert after["stage_pct"] is None


async def test_failed_download_marks_the_document_and_removes_partial_files(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.youtube_ingestion.run_ingestion", ingested)

    async def _failing_download(url, dest_stem, on_progress=None):
        dest_stem.with_suffix(".webm.part").write_bytes(b"\x00" * 10)
        raise RuntimeError("yt-dlp download failed (exit 1): ERROR: Video unavailable")

    with _youtube_ready(_failing_download):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url", json={"url": "https://www.youtube.com/watch?v=t1"}
            )
            doc_id = resp.json()["document_id"]
            await get_ingestion_jobs().get(doc_id)
            status = (await client.get(f"/documents/{doc_id}/status")).json()

    assert status["stage"] == "error"
    assert "Video unavailable" in status["error_message"]
    assert list((tmp_path / "raw").glob(f"{doc_id}*")) == []
    ingested.assert_not_called()


async def test_download_reports_progress(monkeypatch, tmp_path):
    import app.services.youtube_downloader as yt

    captured: list[str] = []
    lines = (
        b"luminary-progress 250 1000 NA\n"
        b"luminary-progress 500 NA 2000\n"  # no total yet: the estimate stands in
        b"luminary-progress 700 NA NA\n"  # neither: nothing to report
        b"[ExtractAudio] Destination: out.wav\n"
        b"luminary-progress 1000 1000 NA\n"
    )

    async def _fake_exec(*args, **kwargs):
        captured.extend(args)
        return _FakeYtDlp(stdout=lines)

    monkeypatch.setattr(yt, "resolve_tool", lambda name: None)
    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)
    seen: list[float] = []

    await yt.download_audio("https://youtu.be/x", tmp_path / "out", on_progress=seen.append)

    assert seen == [0.25, 0.25, 1.0]


async def test_download_keeps_16_bit_flac(monkeypatch, tmp_path):
    """FLAC is lossless only against the WAV it replaces at 16 bits: ffmpeg's default for
    decoded Opus is 24-bit, whose samples differ (decoded PCM checksums did not match)."""
    import app.services.youtube_downloader as yt

    captured: list[str] = []

    async def _fake_exec(*args, **kwargs):
        captured.extend(args)
        return _FakeYtDlp()

    monkeypatch.setattr(yt, "resolve_tool", lambda name: None)
    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)

    await yt.download_audio("https://youtu.be/x", tmp_path / "out")

    assert captured[captured.index("--audio-format") + 1] == "flac"
    assert captured[captured.index("--postprocessor-args") + 1] == "ExtractAudio:-sample_fmt s16"


async def test_download_failure_still_names_yt_dlps_reason(monkeypatch, tmp_path):
    import app.services.youtube_downloader as yt

    async def _fake_exec(*args, **kwargs):
        return _FakeYtDlp(stderr=b"ERROR: [youtube] x: Video unavailable\n", returncode=1)

    monkeypatch.setattr(yt, "resolve_tool", lambda name: None)
    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(RuntimeError, match="Video unavailable"):
        await yt.download_audio("https://youtu.be/x", tmp_path / "out")


async def test_cancelled_download_kills_yt_dlp(monkeypatch, tmp_path):
    """Deleting a document cancels its job; the subprocess must not outlive it."""
    import app.services.youtube_downloader as yt

    proc = _FakeYtDlp(hang=True)

    async def _fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(yt, "resolve_tool", lambda name: None)
    monkeypatch.setattr(yt.asyncio, "create_subprocess_exec", _fake_exec)

    task = asyncio.create_task(yt.download_audio("https://youtu.be/x", tmp_path / "out"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert proc.killed
