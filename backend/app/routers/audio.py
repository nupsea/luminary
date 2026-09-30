"""Endpoints for audio transcription and voice dictation.

Routes: POST /audio/transcribe
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.exceptions import InvalidInput
from app.services.audio_transcriber import get_audio_transcriber

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


class TranscriptionResponse(BaseModel):
    text: str
    duration: float = 0.0


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(None),
) -> TranscriptionResponse:
    """Transcribe a dictated recording; ``language`` is an ISO 639-1 hint."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No audio file uploaded")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".webm", ".wav", ".mp3", ".ogg", ".m4a"}:
        suffix = ".webm"

    content = await file.read()
    if len(content) == 0:
        return TranscriptionResponse(text="", duration=0.0)

    def _run_transcription(data: bytes, file_suffix: str) -> tuple[str, float]:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        try:
            transcriber = get_audio_transcriber()
            import av  # noqa: PLC0415 -- the media extra, absent from the bundle

            try:
                return transcriber.dictate(tmp_path, language=language)
            except av.error.FFmpegError as exc:
                # A raised decode error escapes CORS and reads as a network failure.
                logger.warning(
                    "transcribe: undecodable upload %s (%s, %d bytes, starts %s): %s",
                    file.filename,
                    file.content_type,
                    len(data),
                    data[:4].hex(),
                    exc,
                )
                raise InvalidInput(
                    "The recording could not be read as audio. Try recording again."
                ) from exc
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    text, duration = await asyncio.to_thread(_run_transcription, content, suffix)
    return TranscriptionResponse(text=text, duration=duration)
