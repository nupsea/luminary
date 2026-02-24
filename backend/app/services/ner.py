"""EntityExtractor: GLiNER-based zero-shot named entity recognition.

Loads 'urchade/gliner_multi_pii-v1' on first use and caches to DATA_DIR/models/gliner/.
Extracts entities from chunk texts with custom entity types.
"""

import logging
import uuid
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

ENTITY_TYPES = [
    "PERSON",
    "ORGANIZATION",
    "PLACE",
    "CONCEPT",
    "EVENT",
    "TECHNOLOGY",
    "DATE",
]

_extractor: "EntityExtractor | None" = None


def get_entity_extractor() -> "EntityExtractor":
    global _extractor
    if _extractor is None:
        settings = get_settings()
        _extractor = EntityExtractor(settings.DATA_DIR)
    return _extractor


class EntityExtractor:
    _model = None

    def __init__(self, data_dir: str) -> None:
        self._model_dir = Path(data_dir).expanduser() / "models" / "gliner"
        self._model_dir.mkdir(parents=True, exist_ok=True)

    def _load_model(self):
        """Lazy-load GLiNER model, caching to DATA_DIR/models/gliner/."""
        if self._model is not None:
            return self._model

        from gliner import GLiNER  # noqa: PLC0415

        logger.info("Loading GLiNER model", extra={"model_dir": str(self._model_dir)})
        self._model = GLiNER.from_pretrained(
            "urchade/gliner_multi_pii-v1",
            cache_dir=str(self._model_dir),
        )
        logger.info("GLiNER model loaded")
        return self._model

    def extract(self, chunks: list[dict]) -> list[dict]:
        """Extract named entities from a list of chunk dicts.

        Each chunk dict must have: id (str), document_id (str), text (str).

        Returns list of entity dicts:
            {id, name (normalized lowercase), type, chunk_id, document_id}
        """
        model = self._load_model()
        entities: list[dict] = []

        for chunk in chunks:
            chunk_id = chunk["id"]
            doc_id = chunk["document_id"]
            text = chunk["text"]

            if not text.strip():
                continue

            raw_entities = model.predict_entities(text, ENTITY_TYPES, threshold=0.5)

            for ent in raw_entities:
                name = ent["text"].strip().lower()
                if not name:
                    continue
                entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{name}"))
                entities.append(
                    {
                        "id": entity_id,
                        "name": name,
                        "type": ent["label"],
                        "chunk_id": chunk_id,
                        "document_id": doc_id,
                    }
                )

        return entities
