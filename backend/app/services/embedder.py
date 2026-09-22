import logging
from typing import Any

import numpy as np

from app.services import model_prefetch
from app.services.model_loading import MODEL_LOAD_LOCK

logger = logging.getLogger(__name__)

# bge-small-en-v1.5 is ~133MB (vs ~2.2GB for bge-m3) and fast on CPU.
MODEL_NAME = model_prefetch.EMBEDDER_REPO
BATCH_SIZE = 128  # Larger batches are more efficient for lighter models

# bge-*-en-v1.5 is asymmetric: the query gets an instruction, the passage does
# not. Passages are embedded via encode() (no prefix), so applying this to the
# query side only aligns us with the model's s2p training WITHOUT re-indexing
# the corpus. Omit it and dense retrieval silently underperforms lexical.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class EmbeddingService:
    def __init__(self) -> None:
        self._model: Any = None
        logger.info("EmbeddingService created")

    def _load_model(self) -> None:
        if self._model is not None:
            return
        cache_dir = model_prefetch.cache_dir(model_prefetch.spec_for("embedder"))
        # Cache-only: setup downloads it (model_prefetch), never this path.
        model_prefetch.require_snapshot(cache_dir, MODEL_NAME)
        # The lock must span the construction itself, not just the None check --
        # see app/services/model_loading.py.
        with MODEL_LOAD_LOCK:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(
                MODEL_NAME,
                cache_folder=str(cache_dir),
                device="cpu",
                local_files_only=True,
            )
            logger.info("Loaded %s from the local cache", MODEL_NAME)

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


def embed_query(query: str) -> list[float]:
    return get_embedding_service().encode([QUERY_INSTRUCTION + query])[0]
