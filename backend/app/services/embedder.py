import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 64  # larger batches = fewer round-trips = faster on CPU


def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Apply mean pooling weighted by attention mask."""
    mask = attention_mask[..., np.newaxis].astype(np.float32)
    summed = (token_embeddings * mask).sum(axis=1)
    count = mask.sum(axis=1).clip(min=1e-9)
    return (summed / count).astype(np.float32)


def _normalize(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True).clip(min=1e-12)
    return (embeddings / norms).astype(np.float32)


class EmbeddingService:
    def __init__(self) -> None:
        self._backend: str | None = None
        self._model: Any = None
        self._tokenizer: Any = None
        logger.info("EmbeddingService created")

    def _load_model(self) -> None:
        if self._backend is not None:
            return
        settings = get_settings()
        cache_dir = Path(settings.DATA_DIR).expanduser() / "models" / "bge-m3"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            from optimum.onnxruntime import ORTModelForFeatureExtraction
            from transformers import AutoTokenizer

            # Saved ONNX lives in a dedicated subdirectory so we can check existence
            # independently of the HuggingFace blob cache.
            onnx_dir = cache_dir / "onnx"
            onnx_file = onnx_dir / "model.onnx"
            needs_export = not onnx_file.exists()
            logger.info(
                "Loading BGE-M3 via ONNX Runtime",
                extra={"export": needs_export, "onnx_dir": str(onnx_dir)},
            )
            if needs_export:
                # First run: export from HuggingFace weights and save to onnx_dir
                model = ORTModelForFeatureExtraction.from_pretrained(
                    MODEL_NAME,
                    cache_dir=str(cache_dir),
                    export=True,
                )
                onnx_dir.mkdir(parents=True, exist_ok=True)
                model.save_pretrained(str(onnx_dir))
                logger.info("BGE-M3 ONNX exported and saved", extra={"onnx_dir": str(onnx_dir)})
                self._model = model
            else:
                # Subsequent runs: load directly from saved ONNX (fast, no re-export)
                self._model = ORTModelForFeatureExtraction.from_pretrained(
                    str(onnx_dir),
                    export=False,
                )
            self._tokenizer = AutoTokenizer.from_pretrained(
                MODEL_NAME, cache_dir=str(cache_dir)
            )
            self._backend = "ort"
            logger.info("BGE-M3 loaded via ONNX Runtime")
        except Exception as exc:
            logger.warning(
                "ONNX Runtime load failed, falling back to SentenceTransformer: %s", exc
            )
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(MODEL_NAME, cache_folder=str(cache_dir))
            self._backend = "st"
            logger.info("BGE-M3 loaded via SentenceTransformer")

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts into 1024-dim float embeddings in batches of BATCH_SIZE."""
        self._load_model()
        results: list[list[float]] = []
        total = len(texts)
        for i in range(0, total, BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            if self._backend == "ort":
                batch_emb = self._encode_ort(batch)
            else:
                batch_emb = self._encode_st(batch)
            results.extend(batch_emb)
            done = min(i + BATCH_SIZE, total)
            if done % (BATCH_SIZE * 5) == 0 or done == total:
                logger.debug(
                    "Embedding progress",
                    extra={"done": done, "total": total, "pct": round(done / total * 100)},
                )
        return results

    def _encode_ort(self, texts: list[str]) -> list[list[float]]:
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        outputs = self._model(**encoded)
        token_emb = np.array(outputs.last_hidden_state, dtype=np.float32)
        attn_mask = np.array(encoded["attention_mask"], dtype=np.float32)
        embeddings = _normalize(_mean_pool(token_emb, attn_mask))
        return embeddings.tolist()

    def _encode_st(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return np.array(embeddings, dtype=np.float32).tolist()


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
