"""Tests for the EmbeddingService.

The integration test (test_encode_returns_correct_shape) is skipped unless the
bge-small model is already cached at DATA_DIR/models/bge-small/. This avoids
downloading several GBs of model weights during CI runs.
"""

from pathlib import Path

import pytest


def _model_cached() -> bool:
    from app.config import get_settings

    cache_dir = Path(get_settings().DATA_DIR).expanduser() / "models" / "bge-small"
    return cache_dir.exists() and any(cache_dir.iterdir())


@pytest.fixture
def cached_model_only():
    """Skip unless the model is cached in the DATA_DIR the test will actually use.

    This was a `skipif`, which decides at import time -- before the session fixture
    has pointed DATA_DIR anywhere. It therefore read the developer's own library,
    where the model is cached from real use, and let the test run against an
    isolated directory where it was not: a 22.8s download locally, and a silent skip
    on any machine whose real library happens to be empty. Deciding inside the test
    reads the directory the encode call will read.
    """
    if not _model_cached():
        pytest.skip("BGE-small model not cached at DATA_DIR/models/bge-small/")


# Unit tests — do not load the real model


def test_embedding_service_instantiates():
    """EmbeddingService can be constructed without loading the model."""
    from app.services.embedder import EmbeddingService

    svc = EmbeddingService()
    assert svc._model is None


# Integration test — requires cached model


def test_encode_returns_correct_shape(cached_model_only):
    """encode() returns (N, 384) float embeddings for N texts."""
    from app.services.embedder import EmbeddingService

    svc = EmbeddingService()
    texts = ["hello", "world", "this is a test", "embedding pipeline", "luminary"]
    embeddings = svc.encode(texts)

    assert len(embeddings) == 5
    for emb in embeddings:
        assert len(emb) == 384
        assert all(isinstance(v, float) for v in emb)
