"""The Whisper model dictation uses: chosen by the user, apart from the import model."""

import io
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import audio_transcriber, python_extras
from app.services import components as components_module


@pytest.fixture(autouse=True)
def _whisper_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_transcriber, "_cache_dir", lambda: tmp_path)


async def _dictate() -> MagicMock:
    fake = MagicMock()
    fake.dictate.return_value = ("Capable of handling data.", 2.0)
    with patch("app.routers.audio.get_audio_transcriber", return_value=fake) as loader:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            files = {"file": ("a.webm", io.BytesIO(b"RIFFdummy"), "audio/webm")}
            assert (await c.post("/audio/transcribe", files=files)).status_code == 200
    return loader


async def test_dictation_runs_on_the_chosen_model():
    assert (await _dictate()).call_args.args == ("base",)

    audio_transcriber.choose_dictation_model("large-v3-turbo")
    assert (await _dictate()).call_args.args == ("large-v3-turbo",)


def test_an_unknown_choice_on_disk_reads_as_the_import_model():
    audio_transcriber.choose_dictation_model("tiny")
    assert audio_transcriber.dictation_model() == "base"


def test_the_import_model_and_the_dictation_model_load_separately(monkeypatch):
    built: list[str] = []
    monkeypatch.setattr(
        audio_transcriber, "AudioTranscriber", lambda model_size: built.append(model_size)
    )
    audio_transcriber._loaded.cache_clear()
    try:
        audio_transcriber.get_audio_transcriber()
        audio_transcriber.get_audio_transcriber("base")
        audio_transcriber.get_audio_transcriber("small")
    finally:
        audio_transcriber._loaded.cache_clear()
    # The default and an explicit "base" are one model, loaded once.
    assert built == ["base", "small"]


async def _install(monkeypatch, *, cached: bool, fetch) -> list[dict]:
    monkeypatch.setattr(python_extras, "extra_installed", lambda comp: True)
    monkeypatch.setattr(audio_transcriber, "weights_cached", lambda size=None: cached)
    monkeypatch.setattr(audio_transcriber, "fetch_weights", fetch)
    return [e async for e in components_module.install_component("dictation:small")]


async def test_choosing_a_model_downloads_it_then_switches(monkeypatch):
    fetched: list[str] = []
    events = await _install(monkeypatch, cached=False, fetch=fetched.append)

    assert fetched == ["small"]
    assert events[-1]["state"] == "ready"
    assert audio_transcriber.dictation_model() == "small"


async def test_choosing_an_installed_model_does_not_download(monkeypatch):
    def _no_fetch(size):
        raise AssertionError("weights already on disk; no network")

    events = await _install(monkeypatch, cached=True, fetch=_no_fetch)

    assert events[-1]["state"] == "ready"
    assert audio_transcriber.dictation_model() == "small"


async def test_a_failed_download_keeps_the_previous_model(monkeypatch):
    audio_transcriber.choose_dictation_model("large-v3-turbo")

    def _blocked(size):
        raise ConnectionError("Connection aborted.")

    events = await _install(monkeypatch, cached=False, fetch=_blocked)

    assert events[-1]["state"] == "failed"
    assert "firewall" in events[-1]["detail"]
    assert audio_transcriber.dictation_model() == "large-v3-turbo"


async def test_status_offers_each_dictation_model(monkeypatch):
    async def no_models() -> set[str]:
        return set()

    monkeypatch.setattr(components_module, "_installed_ollama_models", no_models)
    monkeypatch.setattr(python_extras, "packages_present", lambda comp: True)
    monkeypatch.setattr(audio_transcriber, "weights_cached", lambda size=None: size == "base")

    status = await components_module.component_status()
    choices = next(c for c in status if c["id"] == "transcription")["dictation_choices"]

    assert [c["model"] for c in choices] == ["base", "small", "large-v3-turbo"]
    assert [c["installed"] for c in choices] == [True, False, False]
    assert [c["selected"] for c in choices] == [True, False, False]
    assert all(components_module.get_component(f"dictation:{c['model']}") for c in choices)
    assert components_module.get_component("dictation:tiny") is None


async def test_removing_a_dictation_model_falls_back_and_keeps_the_import_model():
    audio_transcriber.repo_dir("small").mkdir()
    audio_transcriber.choose_dictation_model("small")

    with pytest.raises(ValueError, match="stays"):
        await components_module.remove_component("dictation:base")
    await components_module.remove_component("dictation:small")

    assert not audio_transcriber.repo_dir("small").exists()
    assert audio_transcriber.dictation_model() == "base"
