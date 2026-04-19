"""AudioTranscriber -- wraps faster_whisper.WhisperModel.

Returns (segments, duration_seconds) where segments is a list of
{"start": float, "end": float, "text": str} dicts.
"""

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioTranscriber:
    def __init__(self, model_size: str = "base") -> None:
        from faster_whisper import WhisperModel  # noqa: PLC0415

        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("AudioTranscriber: loaded model_size=%s", model_size)

    def transcribe(self, file_path: Path) -> tuple[list[dict], float]:
        """Return (segments, duration_seconds).

        segments: list of {"start": float, "end": float, "text": str}
        """
        segments_iter, info = self._model.transcribe(str(file_path), beam_size=1)
        result = [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in segments_iter
            if seg.text.strip()
        ]
        logger.info(
            "AudioTranscriber: transcribed %d segments, duration=%.1fs",
            len(result),
            info.duration,
        )
        return result, info.duration


@lru_cache(maxsize=1)
def get_audio_transcriber() -> AudioTranscriber:
    from app.config import get_settings  # noqa: PLC0415

    return AudioTranscriber(model_size=get_settings().WHISPER_MODEL_SIZE)
