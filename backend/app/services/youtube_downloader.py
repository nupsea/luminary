"""YouTube audio download service using yt-dlp subprocess.

Uses subprocess (not the yt-dlp Python API) to match the project pattern
for system tools (see: ffmpeg use in ingestion.py).
"""

import asyncio
import json
import logging
from pathlib import Path

from app.services.components import resolve_tool

logger = logging.getLogger(__name__)

_YOUTUBE_URL_PREFIXES = (
    "https://www.youtube.com/watch",
    "https://youtu.be/",
    "https://youtube.com/watch",
    "http://www.youtube.com/watch",
    "http://youtu.be/",
)


def is_youtube_url(url: str) -> bool:
    """Return True if url looks like a YouTube watch URL."""
    return any(url.startswith(p) for p in _YOUTUBE_URL_PREFIXES)


def _ytdlp() -> str:
    """Absolute path to yt-dlp, since the bundled app runs with a minimal PATH."""
    return resolve_tool("yt-dlp") or "yt-dlp"


def check_ytdlp_available() -> bool:
    return resolve_tool("yt-dlp") is not None


def check_ffmpeg_available() -> bool:
    return resolve_tool("ffmpeg") is not None


async def fetch_metadata(url: str) -> dict:
    """Run yt-dlp --dump-json --no-download and return parsed JSON.

    Raises RuntimeError on non-zero exit or invalid JSON.
    """
    proc = await asyncio.create_subprocess_exec(
        _ytdlp(),
        "--dump-json",
        "--no-download",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata fetch failed (exit {proc.returncode})")
    return json.loads(stdout.decode())


def _last_error_line(stderr: bytes | None) -> str:
    """The most useful line of yt-dlp's stderr, trimmed for a UI toast.

    yt-dlp prints warnings before the failure, so the last ERROR line is the
    one that explains the exit code; fall back to the last non-empty line when
    it failed without one.
    """
    text = (stderr or b"").decode("utf-8", "replace").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    chosen = errors[-1] if errors else lines[-1]
    return chosen[:300]


async def download_audio(url: str, dest_stem: Path) -> None:
    """Download audio-only WAV to dest_stem.wav using yt-dlp.

    dest_stem should NOT include an extension -- yt-dlp appends .wav.
    The actual file written will be at dest_stem.with_suffix('.wav').

    Raises RuntimeError on non-zero exit.
    """
    # yt-dlp finds ffmpeg on its own PATH, which is the bundle's minimal one --
    # not wherever `resolve_tool` located the binary. Luminary's own check would
    # pass while the download still died on "ffprobe and ffmpeg not found", so
    # the resolved location has to be handed over explicitly. The *directory* is
    # passed rather than the binary because postprocessing needs ffprobe too,
    # and it sits beside ffmpeg.
    ffmpeg = resolve_tool("ffmpeg")
    location = ["--ffmpeg-location", str(Path(ffmpeg).parent)] if ffmpeg else []
    proc = await asyncio.create_subprocess_exec(
        _ytdlp(),
        "-x",
        "--audio-format",
        "wav",
        "--audio-quality",
        "0",
        *location,
        "-o",
        f"{dest_stem}.%(ext)s",
        url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        # yt-dlp says why on stderr and the reason is actionable: a stale binary
        # gets "HTTP Error 403: Forbidden" on every video, a private or removed
        # video says so, a region block says that. Discarding it left the user
        # with "exit 1" and nothing to act on -- which is how a five-month-old
        # pin went unnoticed.
        detail = _last_error_line(stderr)
        raise RuntimeError(
            f"yt-dlp download failed (exit {proc.returncode}): {detail}"
            if detail
            else f"yt-dlp download failed (exit {proc.returncode})"
        )
    logger.info("yt-dlp downloaded audio to %s.wav", dest_stem)
