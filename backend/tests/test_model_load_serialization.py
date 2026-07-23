"""Torch model construction must be serialized process-wide.

`transformers.from_pretrained` mutates global state while building a model, so
two concurrent loads leave one model with unmaterialized meta parameters and its
`.to(device)` raises "Cannot copy out of meta tensor". Regression test for the
warmup path in main.py, which loads embedder + GLiNER + reranker in parallel
executor threads.
"""

import threading
import time

import pytest

from app.services.model_loading import MODEL_LOAD_LOCK


class _OverlapDetector:
    def __init__(self) -> None:
        self.active = 0
        self.overlapped = False
        self._guard = threading.Lock()

    def build(self, *args, **kwargs):
        with self._guard:
            self.active += 1
            if self.active > 1:
                self.overlapped = True
        time.sleep(0.05)
        with self._guard:
            self.active -= 1
        return object()


@pytest.fixture
def detector(monkeypatch):
    import sentence_transformers

    det = _OverlapDetector()
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", det.build)
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", det.build)
    return det


def _run_concurrently(loaders):
    threads = [threading.Thread(target=fn) for fn in loaders]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_concurrent_loads_do_not_overlap(detector):
    from app.services.embedder import EmbeddingService
    from app.services.retriever_strategies import _CrossEncoderReranker

    loaders = [EmbeddingService()._load_model for _ in range(3)]
    loaders += [_CrossEncoderReranker()._load for _ in range(3)]
    _run_concurrently(loaders)

    assert not detector.overlapped


def test_loader_holds_the_global_lock(monkeypatch):
    import sentence_transformers

    from app.services.embedder import EmbeddingService

    held: list[bool] = []

    def build(*args, **kwargs):
        held.append(MODEL_LOAD_LOCK._is_owned())
        return object()

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", build)
    EmbeddingService()._load_model()

    assert held == [True]
