"""Detection before ingest, and media errors that name an installable component.

Two shipped defects are pinned here:

1. The upload dialog could only show a document's type after it was already in
   the library, which is the wrong moment to discover the type was wrong.
   `POST /documents/detect-type` answers before anything is created.

2. YouTube failed with "ffmpeg is not installed. Install it with: brew install
   ffmpeg" -- advice pointing outside an app that ships an installer for that
   exact component, on a bundle whose minimal PATH may not even find a brew
   install. The check also stopped at the first missing tool and never covered
   transcription, so a user who followed the advice hit a second wall.
"""

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _post_detect(filename: str, body: bytes) -> tuple[int, dict]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/detect-type",
            files={"file": (filename, io.BytesIO(body), "text/plain")},
        )
    return resp.status_code, (resp.json() if resp.content else {})


@pytest.mark.anyio
async def test_detect_type_reads_the_document() -> None:
    technical = (
        "The kernel exposes a system call interface. Each function takes parameters "
        "and returns an integer; a process reads from stdin and writes to stdout, and "
        "the protocol between client and server is a sequence of packets. "
    ) * 200
    status, body = await _post_detect("manual.txt", technical.encode())
    assert status == 200
    assert body["detected"] is True
    assert body["content_type"] in ("tech_book", "tech_article")


@pytest.mark.anyio
async def test_detect_type_creates_nothing(monkeypatch) -> None:
    """The whole point: it answers without putting anything in the library.

    Asserted against the mechanism rather than a row count -- no ingestion job
    is launched and nothing is left in the data directory -- because a count
    that happens to match would pass even if a row were written and removed.
    """
    import app.routers.documents as documents_module

    launched: list[str] = []
    monkeypatch.setattr(
        documents_module.get_ingestion_jobs(),
        "launch",
        lambda doc_id, coro: (launched.append(doc_id), coro.close()),
    )
    data_dir = Path(get_settings().DATA_DIR).expanduser()
    raw_before = sorted(p.name for p in (data_dir / "raw").glob("*")) if (
        data_dir / "raw"
    ).exists() else []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/detect-type",
            files={"file": ("throwaway.txt", io.BytesIO(b"some words here"), "text/plain")},
        )

    assert resp.status_code == 200
    assert launched == [], "detect-type must not start an ingestion job"
    raw_after = sorted(p.name for p in (data_dir / "raw").glob("*")) if (
        data_dir / "raw"
    ).exists() else []
    assert raw_before == raw_after, "detect-type must not leave a file behind"


@pytest.mark.anyio
async def test_detect_type_decides_media_from_the_extension() -> None:
    """Media is classified from a transcript that does not exist yet."""
    for name, expected in (("talk.mp3", "audio"), ("lecture.mp4", "video"), ("novel.epub", "book")):
        status, body = await _post_detect(name, b"\x00\x01binary")
        assert status == 200
        assert body["content_type"] == expected


@pytest.mark.anyio
async def test_detect_type_refuses_an_unsupported_format() -> None:
    status, _ = await _post_detect("thing.xyz", b"whatever")
    assert status == 400


@pytest.mark.anyio
async def test_detect_type_failure_does_not_block_the_upload() -> None:
    """A detection failure reports itself; it must never raise at the caller.

    Ingestion classifies again anyway, so the dialog showing nothing is the
    correct degraded behaviour -- an error here would block adding the file.
    """
    status, body = await _post_detect("empty.txt", b"")
    assert status == 200
    assert "content_type" in body


@pytest.mark.anyio
async def test_youtube_error_names_every_missing_component(monkeypatch) -> None:
    """Not just the first one, and not shell instructions.

    The old check tested yt-dlp then ffmpeg and returned on the first failure,
    never reaching transcription -- so installing ffmpeg bought the user a
    second identical wall.
    """
    import app.routers.documents as documents_module

    async def _no_media_capabilities():
        return {
            "youtube_ingest": {"available": False, "requires": ["transcription", "ffmpeg"]},
        }

    monkeypatch.setattr(documents_module, "capabilities", _no_media_capabilities)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest-url",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), "the client needs component ids, not a sentence"
    assert set(detail["components"]) == {"transcription", "ffmpeg"}
    # The message names the components in words the user sees on the install screen.
    assert "Speech to text" in detail["message"]
    assert "Audio and video support" in detail["message"]
    # And it must not send the user to a package manager.
    assert "brew" not in detail["message"].lower()
    assert "apt" not in detail["message"].lower()
