"""YouTube audio download service using yt-dlp subprocess.

Uses subprocess (not the yt-dlp Python API) to match the project pattern
for system tools (see: ffmpeg use in ingestion.py).
"""

import asyncio
import importlib.util
import json
import logging
import re
import sys
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


def _ytdlp_argv() -> list[str]:
    """yt-dlp as a module of this interpreter when it carries one: the bundled
    Windows launcher `.exe` has the build machine's path compiled in."""
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return [resolve_tool("yt-dlp") or "yt-dlp"]


def check_ytdlp_available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None or resolve_tool("yt-dlp") is not None


def check_ffmpeg_available() -> bool:
    return resolve_tool("ffmpeg") is not None


async def fetch_metadata(url: str) -> dict:
    """Run yt-dlp --dump-json --no-download and return parsed JSON.

    Raises RuntimeError on non-zero exit or invalid JSON.
    """
    proc = await asyncio.create_subprocess_exec(
        *_ytdlp_argv(),
        "--dump-json",
        "--no-download",
        # `--` ends option parsing. Without it a URL beginning with "-" reaches
        # yt-dlp as a flag, which is a file read/write primitive even though
        # nothing here uses a shell. Today `is_youtube_url` happens to block
        # that by requiring an https://youtube.com/... prefix -- this makes it
        # true structurally, so loosening that validator cannot reintroduce it.
        "--",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        # yt-dlp's own ERROR line says why ("Sign in to confirm you're not a bot",
        # "Video unavailable"); the exit code alone gave the user nothing to act on.
        errors = [
            line.removeprefix("ERROR:").strip()
            for line in stderr.decode(errors="replace").splitlines()
            if line.startswith("ERROR:")
        ]
        # First sentence only: the rest is yt-dlp's command-line advice.
        reason = errors[-1].split(". ")[0][:300] if errors else f"exit {proc.returncode}"
        raise RuntimeError(f"YouTube could not be read: {reason}")
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
        *_ytdlp_argv(),
        "-x",
        "--audio-format",
        "wav",
        "--audio-quality",
        "0",
        *location,
        "-o",
        f"{dest_stem}.%(ext)s",
        # See fetch_metadata: `--` ends option parsing so the URL can never be
        # read as a flag.
        "--",
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


_TRACK_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _uploaded_tracks(meta: dict) -> list[str]:
    return [
        k
        for k in meta.get("subtitles") or {}
        if isinstance(k, str) and _TRACK_KEY.fullmatch(k) and k != "live_chat"
    ]


def uploader_caption_language(meta: dict) -> str | None:
    """The key of the uploader's caption track in the language the video is spoken in.

    `subtitles` holds tracks a person uploaded; YouTube's own speech recognition is
    in `automatic_captions` and mishears the same words Whisper does. A track in
    another language is a translation, not what was said, so a video that does not
    declare its language gets no track.
    """
    spoken = meta.get("language")
    if not isinstance(spoken, str) or not spoken:
        return None
    primary = spoken.split("-")[0].casefold()
    matching = [k for k in _uploaded_tracks(meta) if k.split("-")[0].casefold() == primary]
    if not matching:
        return None
    return spoken if spoken in matching else sorted(matching)[0]


async def download_captions(url: str, dest: Path, track: str) -> bool:
    """Write the uploader's `track` as WebVTT to `dest`. False when none arrived.

    Never fatal: without captions the audio is transcribed instead.
    """
    stem = dest.parent / f"{dest.name}.part"
    proc = await asyncio.create_subprocess_exec(
        *_ytdlp_argv(),
        "--skip-download",
        "--write-subs",
        "--no-write-auto-subs",
        f"--sub-langs={track}",
        "--sub-format=vtt",
        "-o",
        f"{stem}.%(ext)s",
        # See fetch_metadata: `--` ends option parsing so the URL can never be
        # read as a flag.
        "--",
        url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    written = stem.with_name(f"{stem.name}.{track}.vtt")
    if proc.returncode != 0 or not written.exists():
        logger.warning("caption track %s not downloaded: %s", track, _last_error_line(stderr))
        written.unlink(missing_ok=True)
        return False
    written.replace(dest)
    return True
