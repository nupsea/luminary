"""Tests for the EmbeddingService.

The integration test (test_encode_returns_correct_shape) is skipped unless the
bge-small model is already cached at DATA_DIR/models/bge-small/. This avoids
downloading several GBs of model weights during CI runs.
"""
from pathlib import Path

import pytest


def _model_cached() -> bool:
    try:
        from app.config import get_settings

        settings = get_settings()
        cache_dir = Path(settings.DATA_DIR).expanduser() / "models" / "bge-small"
        return cache_dir.exists() and any(cache_dir.iterdir())
    except Exception:
        return False


skipif_no_model = pytest.mark.skipif(
    not _model_cached(),
    reason="BGE-small model not cached at DATA_DIR/models/bge-small/",
)


# ---------------------------------------------------------------------------
# Unit tests — do not load the real model
# ---------------------------------------------------------------------------


def test_embedding_service_instantiates():
    """EmbeddingService can be constructed without loading the model."""
    from app.services.embedder import EmbeddingService

    svc = EmbeddingService()
    assert svc._model is None


# ---------------------------------------------------------------------------
# Integration test — requires cached model
# ---------------------------------------------------------------------------


@skipif_no_model
def test_encode_returns_correct_shape():
    """encode() returns (N, 384) float embeddings for N texts."""
    from app.services.embedder import EmbeddingService

    svc = EmbeddingService()
    texts = ["hello", "world", "this is a test", "embedding pipeline", "luminary"]
    embeddings = svc.encode(texts)

    assert len(embeddings) == 5
    for emb in embeddings:
        assert len(emb) == 384
        assert all(isinstance(v, float) for v in emb)
