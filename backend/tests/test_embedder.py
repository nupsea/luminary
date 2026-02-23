"""Tests for the EmbeddingService.

The integration test (test_encode_returns_correct_shape) is skipped unless the
BGE-M3 model is already cached at DATA_DIR/models/bge-m3/. This avoids
downloading several GBs of model weights during CI runs.
"""
from pathlib import Path

import pytest


def _model_cached() -> bool:
    try:
        from app.config import get_settings

        settings = get_settings()
        cache_dir = Path(settings.DATA_DIR).expanduser() / "models" / "bge-m3"
        return cache_dir.exists() and any(cache_dir.iterdir())
    except Exception:
        return False


skipif_no_model = pytest.mark.skipif(
    not _model_cached(),
    reason="BGE-M3 model not cached at DATA_DIR/models/bge-m3/",
)


# ---------------------------------------------------------------------------
# Unit tests — do not load the real model
# ---------------------------------------------------------------------------


def test_embedding_service_instantiates():
    """EmbeddingService can be constructed without loading the model."""
    from app.services.embedder import EmbeddingService

    svc = EmbeddingService()
    assert svc._backend is None
    assert svc._model is None


def test_mean_pool_shape():
    """_mean_pool reduces (B, T, H) -> (B, H) with mask weighting."""
    import numpy as np

    from app.services.embedder import _mean_pool

    B, T, H = 2, 10, 8
    token_emb = np.ones((B, T, H), dtype=np.float32)
    attn_mask = np.ones((B, T), dtype=np.float32)
    result = _mean_pool(token_emb, attn_mask)
    assert result.shape == (B, H)


def test_normalize_unit_length():
    """_normalize returns L2-unit vectors."""
    import numpy as np

    from app.services.embedder import _normalize

    vecs = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)
    normed = _normalize(vecs)
    norms = np.linalg.norm(normed, axis=1)
    assert norms == pytest.approx([1.0, 1.0], abs=1e-6)


# ---------------------------------------------------------------------------
# Integration test — requires cached model
# ---------------------------------------------------------------------------


@skipif_no_model
def test_encode_returns_correct_shape():
    """encode() returns (N, 1024) float embeddings for N texts."""
    from app.services.embedder import EmbeddingService

    svc = EmbeddingService()
    texts = ["hello", "world", "this is a test", "embedding pipeline", "luminary"]
    embeddings = svc.encode(texts)

    assert len(embeddings) == 5
    for emb in embeddings:
        assert len(emb) == 1024
        assert all(isinstance(v, float) for v in emb)
