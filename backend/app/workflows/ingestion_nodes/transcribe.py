"""transcribe_node and the audio-window chunker `_chunk_audio`.

transcribe_node is a pass-through for non-audio/video content. For
audio it dispatches to the AudioTranscriber service; for video it
shells out to ffmpeg first to extract a 16kHz mono WAV, then runs
the same path. Whisper segments are grouped into ~60-second windows
by `_chunk_audio` and stored as `_audio_chunks` so chunk_node can
pick them up downstream.

Also persists `audio_duration_seconds` and the word_count of the
transcript to DocumentModel.
"""

import asyncio
import contextlib
import logging
import shutil
import tempfile
import uuid as _uuid
import wave
from pathlib import Path

from app.database import get_session_factory
from app.repos.document_repo import DocumentRepo
from app.repos.transcript_repo import fetch_transcript_inputs
from app.services import (
    audio_transcriber as _audio_transcriber_module,  # indirect: get_audio_transcriber is patched
)
from app.services import ingestion_progress
from app.services.captions import captions_path, parse_vtt
from app.services.components import resolve_tool
from app.services.transcript_correction import correct_transcript
from app.services.transcript_vocabulary import hotwords
from app.types import MEDIA_FORMATS
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _persist_classification,
    _update_stage,
    detect_register,
    detect_technical_transcript,
)

logger = logging.getLogger(__name__)


def _chunk_audio(
    segments: list[dict],
    doc_id: str,
    window_seconds: float = 60.0,
) -> list[dict]:
    """Group Whisper segments into ~60-second windows.

    Each returned dict has: id, document_id, text, index, start_time, end_time.
    """
    chunks: list[dict] = []
    bucket_texts: list[str] = []
    bucket_start: float = 0.0
    bucket_end: float = 0.0
    chunk_idx: int = 0

    def _flush(start: float, end: float, texts: list[str]) -> None:
        nonlocal chunk_idx
        if not texts:
            return
        chunks.append(
            {
                "id": str(_uuid.uuid4()),
                "document_id": doc_id,
                "text": " ".join(texts),
                "index": chunk_idx,
                "start_time": start,
                "end_time": end,
            }
        )
        chunk_idx += 1

    for seg in segments:
        if not bucket_texts:
            bucket_start = seg["start"]
        if seg["end"] - bucket_start >= window_seconds and bucket_texts:
            _flush(bucket_start, bucket_end, bucket_texts)
            bucket_texts = []
            bucket_start = seg["start"]
        bucket_texts.append(seg["text"])
        bucket_end = seg["end"]

    _flush(bucket_start, bucket_end, bucket_texts)
    return chunks


def _flac_duration(path: Path) -> float | None:
    """From STREAMINFO, the first metadata block: 20-bit sample rate, then 3 + 5 bits
    of channels and depth, then a 36-bit sample count."""
    with path.open("rb") as f:
        head = f.read(26)
    if len(head) < 26 or head[:4] != b"fLaC":
        return None
    bits = int.from_bytes(head[18:26], "big")
    rate, samples = bits >> 44, bits & (2**36 - 1)
    return samples / rate if rate and samples else None


def _audio_duration(path: Path) -> float | None:
    try:
        if path.suffix.lower() == ".flac":
            return _flac_duration(path)
        with contextlib.closing(wave.open(str(path), "rb")) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, OSError, EOFError, ZeroDivisionError):
        return None


async def _transcript(doc_id: str, source: Path, audio: Path) -> tuple[list[dict], float, str]:
    """(segments, duration, transcript_source): the uploader's captions, else primed
    Whisper; then the corrections pass (`transcript_correction`)."""
    captions = captions_path(source)
    segments = parse_vtt(captions.read_text(encoding="utf-8")) if captions.exists() else []
    if segments:
        segments = await correct_transcript(doc_id, segments, ordinary=None)
        return segments, _audio_duration(audio) or segments[-1]["end"], "captions"
    vocabulary, _, _ = await fetch_transcript_inputs(doc_id)
    transcriber = _audio_transcriber_module.get_audio_transcriber()
    # CPU-bound -- run in thread pool to keep event loop free for status polls
    segments, duration = await asyncio.to_thread(
        transcriber.transcribe,
        audio,
        hotwords=hotwords(vocabulary),
        on_progress=lambda f: ingestion_progress.report(doc_id, "transcribing", f),
    )
    # Judging glossary spans is a model call each, and on a long talk outlasts Whisper.
    await _update_stage(doc_id, "correcting")
    segments = await correct_transcript(
        doc_id,
        segments,
        ordinary=transcriber.is_whole_word,
        on_progress=lambda f: ingestion_progress.report(doc_id, "correcting", f),
    )
    return segments, duration, "speech"


async def transcribe_node(state: IngestionState) -> IngestionState:
    """Transcribe audio/video files using faster-whisper.

    For non-audio/video content types this is a pass-through.
    An uploader's caption track beside the audio is read instead of transcribing;
    otherwise Whisper runs, primed with the document's `transcript_vocabulary`.
    For audio files: calls AudioTranscriber directly.
    For video files: runs ffmpeg to extract audio first, then transcribes.
    Builds parsed_document from segments, writes audio_duration_seconds to
    DocumentModel, stores pre-built _audio_chunks.
    """
    fmt = state["format"]
    if fmt not in MEDIA_FORMATS:
        return state

    doc_id = state["document_id"]
    await _update_stage(doc_id, "transcribing")
    logger.info("transcribe_node: start", extra={"doc_id": doc_id, "format": fmt})

    wav_path: Path | None = None
    try:
        fp = Path(state["file_path"])

        # For video: extract audio with ffmpeg before passing to Whisper
        if fmt == "mp4":
            ffmpeg = resolve_tool("ffmpeg")
            if not ffmpeg:
                return {
                    **state,
                    "status": "error",
                    "error": (
                        "Audio and video support (ffmpeg) is not installed. "
                        "Add it from Settings to ingest video files."
                    ),
                }
            wav_path = Path(tempfile.mkdtemp(prefix="luminary-transcribe-")) / "audio.wav"
            proc = await asyncio.create_subprocess_exec(
                ffmpeg,
                "-y",
                "-i",
                str(fp),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(wav_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                return {
                    **state,
                    "status": "error",
                    "error": (
                        "ffmpeg audio extraction failed. Ensure the video file is a valid MP4."
                    ),
                }
            transcribe_fp = wav_path
            logger.info(
                "transcribe_node: ffmpeg extracted audio",
                extra={"doc_id": doc_id, "wav": str(wav_path)},
            )
        else:
            transcribe_fp = fp

        segments, duration, transcript_source = await _transcript(doc_id, fp, transcribe_fp)

        raw_text = " ".join(s["text"] for s in segments)
        audio_chunks = _chunk_audio(segments, doc_id)

        # Sections for section_summarize_node: one section per audio window
        sections = [
            {
                "heading": f"Segment {i + 1} ({c['start_time']:.0f}s-{c['end_time']:.0f}s)",
                "level": 1,
                "text": c["text"],
                "page_start": 0,
                "page_end": 0,
            }
            for i, c in enumerate(audio_chunks)
        ]

        parsed_document = {
            "title": fp.stem,
            "format": fp.suffix.lstrip("."),
            "pages": 0,
            "word_count": len(raw_text.split()),
            "sections": sections,
            "raw_text": raw_text,
        }

        # Persist duration to DocumentModel
        async with get_session_factory()() as session:
            await DocumentRepo(session).update_fields(
                doc_id,
                audio_duration_seconds=duration,
                word_count=len(raw_text.split()),
                transcript_source=transcript_source,
            )
            await session.commit()

        # classify_node runs before transcription, so this is the first point at
        # which a media document has text to judge. Decided once and persisted so
        # entity reindexing reaches the same answer.
        is_technical = await detect_technical_transcript(raw_text)
        register = await detect_register(raw_text)
        if is_technical is not None or register is not None:
            # A technical talk keeps its media type for the player and carries its
            # subject in `domain`.
            legacy_type = "video" if fmt == "mp4" else "audio"
            await _persist_classification(doc_id, legacy_type, is_technical, register)

        logger.info(
            "transcribe_node: done",
            extra={
                "doc_id": doc_id,
                "segments": len(segments),
                "duration": duration,
                "transcript_source": transcript_source,
                "is_technical": is_technical,
            },
        )
        return {
            **state,
            "parsed_document": parsed_document,
            "audio_duration_seconds": duration,
            "is_technical": is_technical,
            "_audio_chunks": audio_chunks,
            "status": "chunking",
        }
    except Exception as exc:
        logger.exception("transcribe_node failed")
        return {**state, "status": "error", "error": str(exc)}
    finally:
        ingestion_progress.clear(doc_id)
        if wav_path is not None:
            shutil.rmtree(wav_path.parent, ignore_errors=True)
