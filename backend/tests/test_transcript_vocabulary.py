"""A YouTube transcript spells the source's own terms: captions first, else primed Whisper."""

import uuid
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import DocumentModel
from app.services.captions import captions_path, parse_vtt
from app.services.transcript_vocabulary import hotwords, vocabulary_from_metadata
from app.services.youtube_downloader import uploader_caption_language

_TALK = {
    "title": "Building RAG pipelines on your laptop",
    "uploader": "DataEngBytes",
    "tags": ["vector search", "LanceDB", "a tag long enough to be a whole sentence typed in"],
    "chapters": [{"title": "Intro"}, {"title": "Why Kimi K3 changes the cost"}],
    "description": (
        "Recorded at DataEngBytes 2025 in Sydney.\n"
        "In this talk Jane Doe walks through retrieval with LanceDB and Kimi K3.\n"
        "00:00 Intro\n"
        "12:30 - Benchmarks\n"
        "Subscribe for more! I hope you enjoy it.\n"
        "Slides: https://example.com/RAGSlides2025 or mail Talks@example.com"
    ),
}


def test_the_terms_a_speech_model_mishears_are_kept():
    vocab = vocabulary_from_metadata(_TALK)
    prompt = hotwords(vocab)
    for term in ("DataEngBytes", "LanceDB", "RAG", "Kimi K3", "Jane Doe", "Sydney"):
        assert term in prompt, term
    assert vocab[:2] == ["Building RAG pipelines on your laptop", "DataEngBytes"]


def test_position_capitals_links_and_numbers_are_not_terms():
    vocab = vocabulary_from_metadata(_TALK)
    joined = " | ".join(vocab)
    for noise in (
        "Intro",
        "Benchmarks",
        "Subscribe",
        "Slides",
        "Why",
        "2025",
        "example.com",
        "RAGSlides",
    ):
        assert noise not in joined, noise
    assert "I" not in vocab
    assert all("whole sentence" not in v for v in vocab)


def test_a_title_case_line_yields_its_spelled_terms_not_the_line():
    vocab = vocabulary_from_metadata(
        {"title": "", "description": "Building Fast Retrieval Pipelines With LanceDB And DuckDB"}
    )
    assert vocab == ["LanceDB", "DuckDB"]


def test_pronouns_lists_and_bylines_from_a_real_description():
    vocab = vocabulary_from_metadata(
        {
            "description": (
                "Since then, I've moved beyond it, combining BM25, Vector search and RAGAS.\n"
                "\n"
                "Anup Sethuram\n"
                "Anup Sethuram is a speaker."
            )
        }
    )
    assert "I've" not in vocab
    assert "BM25" in vocab and "BM25 Vector" not in vocab
    assert vocab[0] == "Anup Sethuram"


def test_without_metadata_there_is_no_prompt():
    """Nothing the system supplies stands in for the source's vocabulary."""
    assert vocabulary_from_metadata({}) == []
    assert hotwords([]) is None
    assert hotwords(None) is None


_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.500 align:start position:0%
We store vectors in <c>LanceDB</c>

2
00:00:03.500 --> 00:00:05.000
[Music]

1:00:05.250 --> 1:00:07.000
R&amp;D on
Kimi K3
"""


def test_captions_parse_to_transcriber_segments():
    assert parse_vtt(_VTT) == [
        {"start": 1.0, "end": 3.5, "text": "We store vectors in LanceDB"},
        {"start": 3605.25, "end": 3607.0, "text": "R&D on Kimi K3"},
    ]


def test_only_an_uploaded_track_in_the_spoken_language_is_used():
    meta = {
        "language": "en",
        "subtitles": {"live_chat": [], "fr": [], "en-GB": []},
        "automatic_captions": {"en": []},
    }
    assert uploader_caption_language(meta) == "en-GB"
    assert uploader_caption_language({**meta, "subtitles": {"en": [], "en-GB": []}}) == "en"
    # YouTube's own recognition, a translation, or an undeclared language: Whisper instead.
    assert uploader_caption_language({**meta, "subtitles": {}}) is None
    assert uploader_caption_language({**meta, "subtitles": {"fr": []}}) is None
    assert uploader_caption_language({**meta, "language": None}) is None
    assert uploader_caption_language({**meta, "subtitles": {"-x": []}, "language": "-x"}) is None


def _write_wav(path: Path, seconds: float) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))


class _RecordingTranscriber:
    def __init__(self) -> None:
        self.hotwords: list[str | None] = []

    def is_whole_word(self, word: str) -> bool:
        return True  # nothing is proposed, so no model is asked

    def transcribe(self, file_path: Path, *, hotwords=None):
        self.hotwords.append(hotwords)
        return [{"start": 0.0, "end": 4.0, "text": "we store vectors in lance db"}], 4.0


async def _ingest_node(factory, wav: Path, vocabulary: list[str] | None):
    from app.workflows.ingestion import transcribe_node

    doc_id = wav.stem
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Talk",
                format="wav",
                content_type="audio",
                file_path=str(wav),
                stage="parsing",
                tags=[],
                transcript_vocabulary=vocabulary,
            )
        )
        await session.commit()
    transcriber = _RecordingTranscriber()
    with (
        patch("app.services.audio_transcriber.get_audio_transcriber", return_value=transcriber),
        patch(
            "app.workflows.ingestion_nodes.transcribe.detect_technical_transcript",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.workflows.ingestion_nodes.transcribe.detect_register",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await transcribe_node(
            {
                "document_id": doc_id,
                "file_path": str(wav),
                "format": "wav",
                "parsed_document": None,
                "content_type": "audio",
                "chunks": None,
                "status": "classifying",
                "error": None,
                "section_summary_count": None,
                "audio_duration_seconds": None,
                "_audio_chunks": None,
            }
        )
    async with factory() as session:
        doc = await session.scalar(select(DocumentModel).where(DocumentModel.id == doc_id))
    return result, doc, transcriber


async def test_captions_replace_speech_recognition(test_db, tmp_path):
    _, factory, _ = test_db
    wav = tmp_path / f"{uuid.uuid4()}.wav"
    _write_wav(wav, 9.0)
    captions_path(wav).write_text(_VTT, encoding="utf-8")

    result, doc, transcriber = await _ingest_node(factory, wav, ["LanceDB"])

    assert result["status"] == "chunking", result.get("error")
    assert transcriber.hotwords == [], "Whisper must not run when the uploader's captions exist"
    assert "LanceDB" in result["parsed_document"]["raw_text"]
    assert doc.transcript_source == "captions"
    # The audio's length, not the last cue's: the player scrubs the whole file.
    assert doc.audio_duration_seconds == pytest.approx(9.0)


async def test_speech_recognition_is_primed_with_the_stored_vocabulary(test_db, tmp_path):
    _, factory, _ = test_db
    wav = tmp_path / f"{uuid.uuid4()}.wav"
    _write_wav(wav, 4.0)

    result, doc, transcriber = await _ingest_node(factory, wav, ["DataEngBytes", "LanceDB"])

    assert result["status"] == "chunking", result.get("error")
    assert transcriber.hotwords == ["DataEngBytes, LanceDB"]
    assert doc.transcript_source == "speech"


async def test_speech_recognition_without_vocabulary_is_unprimed(test_db, tmp_path):
    _, factory, _ = test_db
    wav = tmp_path / f"{uuid.uuid4()}.wav"
    _write_wav(wav, 4.0)

    _, _, transcriber = await _ingest_node(factory, wav, None)

    assert transcriber.hotwords == [None]


@pytest.fixture
def _transcription_installed(monkeypatch):
    from app.services import python_extras

    monkeypatch.setitem(python_extras.EXTRA_WEIGHTS, "transcription", (lambda: True, lambda: None))


async def test_youtube_ingest_keeps_the_vocabulary_and_fetches_captions(
    test_db, monkeypatch, _transcription_installed
):
    _, factory, _ = test_db

    async def _no_ingestion(*_args, **_kwargs):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _no_ingestion)

    async def _fake_download_audio(url: str, dest_stem: Path) -> None:
        dest_stem.with_suffix(".wav").write_bytes(b"\x00" * 100)

    fetch_captions = AsyncMock(return_value=True)
    meta = {**_TALK, "id": "abc", "language": "en", "subtitles": {"en": []}}
    with (
        patch("app.services.youtube_downloader.check_ytdlp_available", return_value=True),
        patch("app.services.youtube_downloader.check_ffmpeg_available", return_value=True),
        patch("app.services.youtube_downloader.fetch_metadata", new=AsyncMock(return_value=meta)),
        patch(
            "app.services.youtube_downloader.download_audio",
            new=AsyncMock(side_effect=_fake_download_audio),
        ),
        patch("app.services.youtube_downloader.download_captions", new=fetch_captions),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url", json={"url": "https://www.youtube.com/watch?v=abc"}
            )

    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]
    async with factory() as session:
        doc = await session.scalar(select(DocumentModel).where(DocumentModel.id == doc_id))
    assert "DataEngBytes" in doc.transcript_vocabulary
    (url, dest, track), _ = fetch_captions.call_args
    assert track == "en"
    assert dest == captions_path(Path(doc.file_path))
