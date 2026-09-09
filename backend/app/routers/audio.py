"""Endpoints for audio transcription and voice dictation.

Routes: POST /audio/transcribe
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.audio_transcriber import get_audio_transcriber

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


class TranscriptionResponse(BaseModel):
    text: str
    duration: float = 0.0


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(file: UploadFile = File(...)) -> TranscriptionResponse:
    """Transcribe an audio recording into text using faster-whisper."""
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
            segments, duration = transcriber.transcribe(tmp_path)
            full_text = " ".join(seg["text"] for seg in segments).strip()
            return full_text, duration
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    text, duration = await asyncio.to_thread(_run_transcription, content, suffix)
    return TranscriptionResponse(text=text, duration=duration)
