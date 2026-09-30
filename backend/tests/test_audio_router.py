"""Tests for POST /audio/transcribe."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_transcribe_empty_file():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("test.webm", io.BytesIO(b""), "audio/webm")}
        response = await client.post("/audio/transcribe", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == ""
        assert data["duration"] == 0.0


@pytest.mark.asyncio
async def test_transcribe_audio_success():
    fake_transcriber = MagicMock()
    fake_transcriber.dictate.return_value = ("Hello world. This is a test explanation.", 5.0)

    with patch("app.routers.audio.get_audio_transcriber", return_value=fake_transcriber):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("test.webm", io.BytesIO(b"RIFFdummydata"), "audio/webm")}
            response = await client.post(
                "/audio/transcribe", files=files, data={"language": "en"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["text"] == "Hello world. This is a test explanation."
            assert data["duration"] == 5.0
            assert fake_transcriber.dictate.call_args.kwargs == {"language": "en"}


def _webm_tone(seconds: float = 1.0) -> bytes:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    buf = io.BytesIO()
    out = av.open(buf, mode="w", format="webm")
    stream = out.add_stream("libopus", rate=48000)
    stream.layout = "mono"
    n = int(48000 * seconds)
    pcm = (0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / 48000)).astype(np.float32)
    for i in range(0, n, 960):
        frame = av.AudioFrame.from_ndarray(pcm[None, i : i + 960], format="flt", layout="mono")
        frame.rate = 48000
        for packet in stream.encode(frame):
            out.mux(packet)
    for packet in stream.encode(None):
        out.mux(packet)
    out.close()
    return buf.getvalue()


@pytest.mark.asyncio
async def test_undecodable_recording_is_a_422_the_browser_can_read():
    """A WebM missing its header (a recording's later chunks with no first one)
    must answer 422 with CORS headers. Raised, it became a bare 500 outside the
    CORS middleware, which a cross-origin browser reports as a network failure."""
    from faster_whisper.audio import decode_audio

    fake_transcriber = MagicMock()
    fake_transcriber.dictate.side_effect = lambda path, language: (decode_audio(str(path)), 0.0)
    headerless = _webm_tone()[300:]

    with patch("app.routers.audio.get_audio_transcriber", return_value=fake_transcriber):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            files = {"file": ("voice_recording.webm", io.BytesIO(headerless), "audio/webm")}
            response = await client.post(
                "/audio/transcribe", files=files, headers={"Origin": "http://localhost:5173"}
            )

    assert response.status_code == 422
    assert "could not be read as audio" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize(("hint", "pinned"), [("en", "en"), ("xx", None), (None, None)])
def test_dictate_pins_only_a_language_whisper_knows(hint, pinned):
    """A short clip is misdetected (Latin, p=0.40), so a known hint is pinned; an unknown
    one falls back to detection rather than failing the transcription."""
    pytest.importorskip("faster_whisper")
    from types import SimpleNamespace

    from app.services.audio_transcriber import AudioTranscriber

    model = MagicMock()
    model.transcribe.return_value = (
        [SimpleNamespace(text=" Mostly with her mother. "), SimpleNamespace(text=" ")],
        SimpleNamespace(duration=2.0, language="en", language_probability=0.9),
    )
    transcriber = AudioTranscriber.__new__(AudioTranscriber)
    transcriber._model = model

    assert transcriber.dictate(Path("clip.webm"), language=hint) == (
        "Mostly with her mother.",
        2.0,
    )
    kwargs = model.transcribe.call_args.kwargs
    assert kwargs["language"] == pinned
    assert kwargs["vad_filter"] is True
    assert "initial_prompt" not in kwargs
