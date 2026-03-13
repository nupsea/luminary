import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

# Switch to a faster, lighter model for local-first performance.
# bge-small-en-v1.5 is ~133MB (vs ~2.2GB for bge-m3) and extremely fast on CPU.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 128  # Larger batches are more efficient for lighter models


class EmbeddingService:
    def __init__(self) -> None:
        self._model: Any = None
        logger.info("EmbeddingService created")

    def _load_model(self) -> None:
        if self._model is not None:
            return
        settings = get_settings()
        cache_dir = Path(settings.DATA_DIR).expanduser() / "models" / "bge-small"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Use SentenceTransformer directly. It is highly optimized for CPU batching
        # and manages its own internal thread pool more effectively than a raw
        # ONNX loop for this specific task.
        from sentence_transformers import SentenceTransformer

        try:
            self._model = SentenceTransformer(MODEL_NAME, cache_folder=str(cache_dir))
            logger.info("Loaded %s via SentenceTransformer", MODEL_NAME)
        except Exception as exc:
            logger.error("Failed to load embedding model: %s", exc)
            raise

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts into float embeddings in batches of BATCH_SIZE."""
        self._load_model()
        if not texts:
            return []

        total = len(texts)
        logger.info("Encoding %d texts", total)

        # sentence-transformers.encode handles batching internally and is
        # optimized for multi-core CPUs.
        embeddings = self._model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        return np.array(embeddings, dtype=np.float32).tolist()


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
