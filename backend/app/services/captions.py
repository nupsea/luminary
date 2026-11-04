"""An uploader's caption track, stored beside the audio and read as transcript segments."""

import html
import re
from pathlib import Path

from app.services.source_bundle import bundle_of, read_manifest

_TIMING = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
)
_TAG = re.compile(r"<[^>]+>")
# A cue that is only a sound description ("[Music]", "♪ ♪") is not speech.
_SOUND_CUE = re.compile(r"^(?:\[[^\]]*\]|\([^)]*\)|[♪\s]+)$")


def captions_path(audio_path: Path) -> Path:
    """`raw/<doc_id>.captions.vtt`: the document's `raw/<doc_id>.*` cleanup removes it too."""
    return audio_path.with_suffix(".captions.vtt")


def captions_for(audio_path: Path) -> Path | None:
    """The caption track stored with this audio: the one its bundle's manifest names, else
    the file beside it."""
    bundle = bundle_of(audio_path)
    if bundle is None:
        return captions_path(audio_path)
    captions = getattr(read_manifest(bundle).media, "captions", None)
    return bundle / captions if captions else None


def _seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(text: str) -> list[dict]:
    """Cues as `{"start", "end", "text"}`, the shape AudioTranscriber returns."""
    segments: list[dict] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        timing_at = next((i for i, ln in enumerate(lines) if _TIMING.search(ln)), None)
        if timing_at is None:
            continue
        g = _TIMING.search(lines[timing_at]).groups()  # type: ignore[union-attr]
        body = " ".join(_TAG.sub("", ln) for ln in lines[timing_at + 1 :])
        body = " ".join(html.unescape(body).split())
        if not body or _SOUND_CUE.match(body):
            continue
        segments.append({"start": _seconds(*g[:4]), "end": _seconds(*g[4:]), "text": body})
    return segments
