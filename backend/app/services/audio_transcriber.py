"""AudioTranscriber -- wraps faster_whisper.WhisperModel.

Returns (segments, duration_seconds) where segments is a list of
{"start": float, "end": float, "text": str} dicts.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from app.config import get_settings
from app.exceptions import ModelNotDownloaded
from app.full_extras import require_extra
from app.storage import machine_root

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    return machine_root() / "models" / "whisper"


_MB = 1024**2


class DictationModel(NamedTuple):
    repo_id: str
    size_bytes: int
    trade_off: str


# A dictated answer lasts seconds, so it can afford a larger model than an hour of
# imported audio. The user picks it; imports stay on `WHISPER_MODEL_SIZE`.
DICTATION_MODELS: dict[str, DictationModel] = {
    "base": DictationModel(
        "Systran/faster-whisper-base",
        145 * _MB,
        "The model audio import uses. Quick, but often mishears accents.",
    ),
    "small": DictationModel(
        "Systran/faster-whisper-small",
        485 * _MB,
        "Much better with accents, and still quick on a short answer.",
    ),
    "large-v3-turbo": DictationModel(
        "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        1620 * _MB,
        "Close to Whisper's best with accents. A few seconds slower per answer, "
        "and about 1.5 GB of memory while dictating.",
    ),
}


def repo_dir(model_size: str) -> Path:
    """The model's own entry in the Hugging Face cache, beside the other sizes."""
    return _cache_dir() / f"models--{DICTATION_MODELS[model_size].repo_id.replace('/', '--')}"


def _choice_file() -> Path:
    return _cache_dir() / "dictation_model"


def dictation_model() -> str:
    """The Whisper model dictation uses: the user's choice, else the import model."""
    try:
        chosen = _choice_file().read_text().strip()
    except OSError:
        chosen = ""
    return chosen if chosen in DICTATION_MODELS else get_settings().WHISPER_MODEL_SIZE


def choose_dictation_model(model_size: str | None) -> None:
    """Record the choice beside the weights: a machine's models serve every library."""
    path = _choice_file()
    if model_size is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model_size)


def weights_cached(model_size: str | None = None) -> bool:
    """Whether these Whisper weights (default: the import model's) are on disk. Offline."""
    from faster_whisper.utils import download_model  # noqa: PLC0415

    try:
        download_model(
            model_size or get_settings().WHISPER_MODEL_SIZE,
            local_files_only=True,
            cache_dir=str(_cache_dir()),
        )
    except Exception:
        return False
    return True


def fetch_weights(model_size: str | None = None) -> None:
    """Download Whisper weights (default: the import model's) as part of an install."""
    from faster_whisper.utils import download_model  # noqa: PLC0415

    _cache_dir().mkdir(parents=True, exist_ok=True)
    download_model(model_size or get_settings().WHISPER_MODEL_SIZE, cache_dir=str(_cache_dir()))


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
            if weights_cached(model_size):
                raise
            raise ModelNotDownloaded(
                f"The Whisper '{model_size}' model is not downloaded. "
                "Install Speech to text again from Settings to download it.",
                model=f"whisper-{model_size}",
            ) from exc
        logger.info("AudioTranscriber: loaded model_size=%s from local cache", model_size)

    def transcribe(
        self,
        file_path: Path,
        *,
        hotwords: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> tuple[list[dict], float]:
        """Return (segments, duration_seconds).

        segments: list of {"start": float, "end": float, "text": str}
        `on_progress` receives the fraction of the audio transcribed so far.

        `hotwords` primes every 30 s window, unlike `initial_prompt`, which only
        reaches the first. A primed model can emit its prompt over silence (see
        `dictate`), so silence is cut out first whenever there is a prompt.
        """
        segments_iter, info = self._model.transcribe(
            str(file_path), beam_size=1, hotwords=hotwords, vad_filter=hotwords is not None
        )
        result = []
        for seg in segments_iter:
            if on_progress is not None and info.duration:
                on_progress(seg.end / info.duration)
            if seg.text.strip():
                result.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        logger.info(
            "AudioTranscriber: transcribed %d segments, duration=%.1fs",
            len(result),
            info.duration,
        )
        return result, info.duration

    def is_whole_word(self, word: str) -> bool:
        """Whether the speech model's own vocabulary holds `word` as one token.

        The tokenizer writes the commonest words as a bare space marker then the
        word ("Ġ", "that"), so that form counts as whole too.
        """
        tokens = self._model.hf_tokenizer.encode(
            " " + word.casefold(), add_special_tokens=False
        ).tokens
        return len(tokens) == 1 or (len(tokens) == 2 and tokens[0] == "Ġ")

    def dictate(self, file_path: Path, *, language: str | None) -> tuple[str, float]:
        """Transcribe a short spoken answer; returns (text, duration_seconds).

        Language detection on a 3-5 s clip is a coin toss, so the caller's language is
        pinned when Whisper knows it. No ``initial_prompt``: primed with the question,
        Whisper returned the question itself as the learner's answer on noisy clips.
        """
        from faster_whisper.tokenizer import _LANGUAGE_CODES  # noqa: PLC0415

        segments_iter, info = self._model.transcribe(
            str(file_path),
            beam_size=5,
            language=language if language in _LANGUAGE_CODES else None,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments_iter if seg.text.strip())
        logger.info(
            "AudioTranscriber: dictated %.1fs, language=%s p=%.2f",
            info.duration,
            info.language,
            info.language_probability,
        )
        return text, info.duration


def get_audio_transcriber(model_size: str | None = None) -> AudioTranscriber:
    return _loaded(model_size or get_settings().WHISPER_MODEL_SIZE)


# Two: the import model and the dictation model stay loaded side by side.
@lru_cache(maxsize=2)
def _loaded(model_size: str) -> AudioTranscriber:
    return AudioTranscriber(model_size=model_size)
