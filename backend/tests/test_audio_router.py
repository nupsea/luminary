"""Tests for POST /audio/transcribe."""

import io
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
    fake_transcriber.transcribe.return_value = (
        [
            {"start": 0.0, "end": 2.5, "text": "Hello world."},
            {"start": 2.5, "end": 5.0, "text": "This is a test explanation."},
        ],
        5.0,
    )

    with patch("app.routers.audio.get_audio_transcriber", return_value=fake_transcriber):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("test.webm", io.BytesIO(b"RIFFdummydata"), "audio/webm")}
            response = await client.post("/audio/transcribe", files=files)
            assert response.status_code == 200
            data = response.json()
            assert data["text"] == "Hello world. This is a test explanation."
            assert data["duration"] == 5.0
            fake_transcriber.transcribe.assert_called_once()
