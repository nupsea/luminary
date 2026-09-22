"""AudioTranscriber -- wraps faster_whisper.WhisperModel.

Returns (segments, duration_seconds) where segments is a list of
{"start": float, "end": float, "text": str} dicts.
"""

import logging
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.exceptions import ModelNotDownloaded
from app.full_extras import require_extra

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    return Path(get_settings().DATA_DIR).expanduser() / "models" / "whisper"


def weights_cached() -> bool:
    """Whether the configured Whisper weights are on disk. Never touches the network."""
    from faster_whisper.utils import download_model  # noqa: PLC0415

    try:
        download_model(
            get_settings().WHISPER_MODEL_SIZE, local_files_only=True, cache_dir=str(_cache_dir())
        )
    except Exception:
        return False
    return True


def fetch_weights() -> None:
    """Download the configured Whisper weights: part of installing the component."""
    from faster_whisper.utils import download_model  # noqa: PLC0415

    _cache_dir().mkdir(parents=True, exist_ok=True)
    download_model(get_settings().WHISPER_MODEL_SIZE, cache_dir=str(_cache_dir()))


class AudioTranscriber:
    def __init__(self, model_size: str = "base") -> None:
        # Absent from the distributed bundle for licensing reasons; the user
        # installs it as the "transcription" component. See docs/desktop-bundle.md.
        require_extra("faster_whisper", "Audio transcription", group="media")

        from faster_whisper import WhisperModel  # noqa: PLC0415

        # Cache-only: installing the component downloads the weights
        # (`fetch_weights`), never a transcription.
        try:
            self._model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                download_root=str(_cache_dir()),
                local_files_only=True,
            )
        except Exception as exc:
            if weights_cached():
                raise
            raise ModelNotDownloaded(
                f"The Whisper '{model_size}' model is not downloaded. "
                "Install Speech to text again from Settings to download it.",
                model=f"whisper-{model_size}",
            ) from exc
        logger.info("AudioTranscriber: loaded model_size=%s from local cache", model_size)

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
