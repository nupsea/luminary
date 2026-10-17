"""How far a long ingestion stage has got: the audio download and transcription.

In memory only: an ingestion does not survive a restart (`main.py` fails it at
startup), so neither does its progress. Written from worker threads; a dict
assignment is atomic under the GIL.
"""

_progress: dict[str, tuple[str, float]] = {}


def report(document_id: str, stage: str, fraction: float) -> None:
    _progress[document_id] = (stage, min(max(fraction, 0.0), 1.0))


def clear(document_id: str) -> None:
    _progress.pop(document_id, None)


def stage_fraction(document_id: str, stage: str) -> float | None:
    """The reported fraction, only while the document is still in that stage."""
    entry = _progress.get(document_id)
    return entry[1] if entry is not None and entry[0] == stage else None
