"""A running app never downloads a model, and never phones home by default.

Every loader used to try the cache and then fall back to downloading. On a
network that blocks huggingface.co that fallback ran on every request -- each
one waiting out a timeout, and each one logged by the network's filter -- while
ingest and search failed. Weights now arrive only through an explicit
provisioning step: setup (`model_prefetch`) or a component install. A loader
with an empty cache raises `ModelNotDownloaded` without constructing anything.
"""

import os
import sys
import types
from pathlib import Path

import pytest

from app.exceptions import ModelNotDownloaded
from app.services import model_prefetch


def _snapshot(root: Path, repo_id: str, files: dict[str, str]) -> None:
    snap = root / f"models--{repo_id.replace('/', '--')}" / "snapshots" / "rev"
    snap.mkdir(parents=True)
    for name, body in files.items():
        (snap / name).write_text(body)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def build(self, *args, **kwargs):
        self.calls.append(kwargs)
        return object()


@pytest.fixture
def empty_models(monkeypatch, tmp_path):
    monkeypatch.setattr(model_prefetch, "models_root", lambda: tmp_path)
    return tmp_path


def test_third_party_phone_home_is_off_before_any_library_loads():
    """`import litellm` fetches a price list from GitHub unless told not to."""
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"].lower() == "true"
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_embedder_with_no_cache_raises_and_never_constructs(monkeypatch, empty_models):
    import sentence_transformers

    from app.services.embedder import EmbeddingService

    rec = _Recorder()
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", rec.build)

    with pytest.raises(ModelNotDownloaded):
        EmbeddingService()._load_model()
    assert rec.calls == [], "a loader with an empty cache must not attempt a load"


def test_reranker_with_no_cache_raises_and_never_constructs(monkeypatch, empty_models):
    import sentence_transformers

    from app.services.retriever_strategies import _CrossEncoderReranker

    rec = _Recorder()
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", rec.build)

    with pytest.raises(ModelNotDownloaded):
        _CrossEncoderReranker()._load()
    assert rec.calls == []


def test_ner_with_no_cache_raises_and_never_constructs(monkeypatch, tmp_path):
    import gliner

    from app.services.ner import EntityExtractor

    rec = _Recorder()
    monkeypatch.setattr(gliner.GLiNER, "from_pretrained", rec.build)
    monkeypatch.setattr(EntityExtractor, "_model", None)

    with pytest.raises(ModelNotDownloaded):
        EntityExtractor(str(tmp_path), model_id="org/gliner-x")._load_model()
    assert rec.calls == []


def test_cached_loads_are_cache_only(monkeypatch, empty_models):
    import sentence_transformers

    from app.services.embedder import EmbeddingService
    from app.services.retriever_strategies import _CrossEncoderReranker

    for key in ("embedder", "reranker"):
        spec = model_prefetch.spec_for(key)
        _snapshot(model_prefetch.cache_dir(spec), spec.repo_id, {"config.json": "{}"})

    rec = _Recorder()
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", rec.build)
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", rec.build)
    EmbeddingService()._load_model()
    _CrossEncoderReranker()._load()

    assert [c["local_files_only"] for c in rec.calls] == [True, True]


@pytest.mark.parametrize("download_succeeds", [True, False])
def test_a_load_during_setup_waits_for_that_download(monkeypatch, tmp_path, download_succeeds):
    """A first ingest can arrive while setup is still fetching the embedder. It
    waits for that download instead of failing, or starting a second one."""
    import threading

    done = threading.Event()
    monkeypatch.setitem(model_prefetch._in_flight, "org/model", done)

    def finish():
        if download_succeeds:
            _snapshot(tmp_path, "org/model", {"config.json": "{}"})
        done.set()

    threading.Timer(0.1, finish).start()
    if download_succeeds:
        model_prefetch.require_snapshot(tmp_path, "org/model")
    else:
        with pytest.raises(ModelNotDownloaded):
            model_prefetch.require_snapshot(tmp_path, "org/model")


def test_gliner_is_not_cached_without_its_tokenizer_base(tmp_path):
    """GLiNER builds its tokenizer from the encoder named in its config, so a
    cached checkpoint alone fails a cache-only load."""
    config = '{"model_name": "org/encoder"}'
    _snapshot(tmp_path, "org/gliner-x", {"gliner_config.json": config})
    assert model_prefetch.tokenizer_base(tmp_path, "org/gliner-x") == "org/encoder"
    assert model_prefetch.snapshot_present(tmp_path, "org/gliner-x") is False

    _snapshot(tmp_path, "org/encoder", {"tokenizer_config.json": "{}"})
    assert model_prefetch.snapshot_present(tmp_path, "org/gliner-x") is True


def test_setup_download_fetches_the_gliner_tokenizer_base(monkeypatch, tmp_path):
    """The loader's online fallback used to fetch these files on first use."""
    fetched: list[tuple[str, list | None]] = []

    def fake_snapshot_download(repo_id, cache_dir, ignore_patterns=None, allow_patterns=None):
        fetched.append((repo_id, allow_patterns))
        if repo_id == "org/gliner-x":
            _snapshot(Path(cache_dir), repo_id, {"gliner_config.json": '{"model_name": "org/enc"}'})

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    spec = model_prefetch.ModelSpec("ner", "org/gliner-x", "gliner", 1)
    model_prefetch._download(spec, tmp_path)

    assert [repo for repo, _ in fetched] == ["org/gliner-x", "org/enc"]
    allow = fetched[1][1]
    assert "tokenizer*" in allow and "*.bin" not in allow, "tokenizer files only, no weights"


def test_whisper_with_no_cache_raises_instead_of_downloading(monkeypatch):
    from app.services import audio_transcriber

    calls: list[dict] = []

    def whisper_model(*args, **kwargs):
        calls.append(kwargs)
        raise OSError("not in cache")

    def download_model(*args, **kwargs):
        raise OSError("not in cache")

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = whisper_model
    fake_utils = types.ModuleType("faster_whisper.utils")
    fake_utils.download_model = download_model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", fake_utils)
    monkeypatch.setattr(audio_transcriber, "require_extra", lambda *a, **k: None)

    with pytest.raises(ModelNotDownloaded):
        audio_transcriber.AudioTranscriber("base")
    assert [c["local_files_only"] for c in calls] == [True]
