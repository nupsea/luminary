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
import logging
import shutil
import tempfile
import uuid as _uuid
from pathlib import Path

from sqlalchemy import update as _update

from app.database import get_session_factory
from app.models import DocumentModel
from app.services import (
    audio_transcriber as _audio_transcriber_module,  # indirect: get_audio_transcriber is patched
)
from app.services.components import resolve_tool
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _persist_is_technical,
    _update_stage,
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


async def transcribe_node(state: IngestionState) -> IngestionState:
    """Transcribe audio/video files using faster-whisper.

    For non-audio/video content types this is a pass-through.
    For audio files: calls AudioTranscriber directly.
    For video files: runs ffmpeg to extract audio first, then transcribes.
    Builds parsed_document from segments, writes audio_duration_seconds to
    DocumentModel, stores pre-built _audio_chunks.
    """
    content_type = state.get("content_type")
    if content_type not in ("audio", "video"):
        return state

    doc_id = state["document_id"]
    await _update_stage(doc_id, "transcribing")
    logger.info("transcribe_node: start", extra={"doc_id": doc_id, "content_type": content_type})

    wav_path: Path | None = None
    try:
        fp = Path(state["file_path"])

        # For video: extract audio with ffmpeg before passing to Whisper
        if content_type == "video":
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

        transcriber = _audio_transcriber_module.get_audio_transcriber()
        loop = asyncio.get_running_loop()
        # CPU-bound -- run in thread pool to keep event loop free for status polls
        segments, duration = await loop.run_in_executor(None, transcriber.transcribe, transcribe_fp)

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
            await session.execute(
                _update(DocumentModel)
                .where(DocumentModel.id == doc_id)
                .values(
                    audio_duration_seconds=duration,
                    word_count=len(raw_text.split()),
                )
            )
            await session.commit()

        # classify_node runs before transcription, so this is the first point at
        # which a media document has text to judge. Decided once and persisted so
        # entity reindexing reaches the same answer.
        is_technical = await detect_technical_transcript(raw_text)
        if is_technical is not None:
            await _persist_is_technical(doc_id, is_technical)

        logger.info(
            "transcribe_node: done",
            extra={
                "doc_id": doc_id,
                "segments": len(segments),
                "duration": duration,
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
        if wav_path is not None:
            shutil.rmtree(wav_path.parent, ignore_errors=True)
