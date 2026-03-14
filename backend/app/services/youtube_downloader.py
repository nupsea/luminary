"""YouTube audio download service using yt-dlp subprocess.

Uses subprocess (not the yt-dlp Python API) to match the project pattern
for system tools (see: ffmpeg use in ingestion.py).
"""
import asyncio
import json
import logging
import shutil
from pathlib import Path

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


def check_ytdlp_available() -> bool:
    """Return True if the yt-dlp binary is available on PATH."""
    return shutil.which("yt-dlp") is not None


def check_ffmpeg_available() -> bool:
    """Return True if the ffmpeg binary is available on PATH."""
    return shutil.which("ffmpeg") is not None


async def fetch_metadata(url: str) -> dict:
    """Run yt-dlp --dump-json --no-download and return parsed JSON.

    Raises RuntimeError on non-zero exit or invalid JSON.
    """
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "--dump-json", "--no-download", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata fetch failed (exit {proc.returncode})")
    return json.loads(stdout.decode())


async def download_audio(url: str, dest_stem: Path) -> None:
    """Download audio-only WAV to dest_stem.wav using yt-dlp.

    dest_stem should NOT include an extension -- yt-dlp appends .wav.
    The actual file written will be at dest_stem.with_suffix('.wav').

    Raises RuntimeError on non-zero exit.
    """
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-x", "--audio-format", "wav", "--audio-quality", "0",
        "-o", f"{dest_stem}.%(ext)s",
        url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp download failed (exit {proc.returncode})")
    logger.info("yt-dlp downloaded audio to %s.wav", dest_stem)
