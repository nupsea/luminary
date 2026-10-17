"""A long ingestion stage reports how far it has got, and only while it is that stage."""

from pathlib import Path
from types import SimpleNamespace

from app.services import ingestion_progress
from app.services.audio_transcriber import AudioTranscriber
from app.workflows.ingestion_nodes._shared import STAGE_PROGRESS, stage_progress_pct


def test_a_reported_fraction_is_read_only_in_its_own_stage():
    ingestion_progress.report("d1", "downloading", 0.4)
    try:
        assert ingestion_progress.stage_fraction("d1", "downloading") == 0.4
        # The download's last report must not pose as transcription progress.
        assert ingestion_progress.stage_fraction("d1", "transcribing") is None
    finally:
        ingestion_progress.clear("d1")
    assert ingestion_progress.stage_fraction("d1", "downloading") is None


def test_transcription_and_correction_span_up_to_chunking():
    """Classify runs before transcription and writes no stage, so the span ends at chunking."""
    assert stage_progress_pct("transcribing", None) == STAGE_PROGRESS["transcribing"]
    assert stage_progress_pct("transcribing", 1.0) == STAGE_PROGRESS["correcting"]
    assert stage_progress_pct("correcting", 1.0) == STAGE_PROGRESS["chunking"]
    assert stage_progress_pct("downloading", 1.0) == STAGE_PROGRESS["parsing"]
    # A stage that reports nothing stays where it starts.
    assert stage_progress_pct("embedding", 0.5) == STAGE_PROGRESS["embedding"]


def test_the_transcriber_reports_each_segment_against_the_duration():
    segments = [
        SimpleNamespace(start=0.0, end=30.0, text=" one"),
        SimpleNamespace(start=30.0, end=60.0, text="  "),  # silence still advances
        SimpleNamespace(start=60.0, end=120.0, text=" two"),
    ]

    class _Model:
        def transcribe(self, *_args, **_kwargs):
            return iter(segments), SimpleNamespace(duration=120.0)

    transcriber = AudioTranscriber.__new__(AudioTranscriber)
    transcriber._model = _Model()
    seen: list[float] = []

    result, duration = transcriber.transcribe(Path("talk.wav"), on_progress=seen.append)

    assert seen == [0.25, 0.5, 1.0]
    assert [s["text"] for s in result] == ["one", "two"]
    assert duration == 120.0


async def test_correction_reports_each_candidate_before_judging_it(monkeypatch):
    from app.services import transcript_correction as tc

    async def _judge(_segments, cand):
        return cand == "b"

    monkeypatch.setattr(tc, "judge", _judge)
    seen: list[float] = []

    chosen = await tc._judged([], ["a", "b", "c", "d"], seen.append)

    assert seen == [0.0, 0.25, 0.5, 0.75]
    assert chosen == {"b"}
