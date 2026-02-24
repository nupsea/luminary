import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

from app.config import get_settings

logger = logging.getLogger(__name__)

TABLE_NAME = "chunk_vectors"

SCHEMA = pa.schema(
    [
        pa.field("chunk_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("content_type", pa.string()),
        pa.field("section_heading", pa.string()),
        pa.field("page", pa.int32()),
        pa.field("speaker", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),
    ]
)


class LanceDBService:
    def __init__(self) -> None:
        self._db: Any = None

    def _connect(self) -> None:
        if self._db is not None:
            return
        import lancedb

        settings = get_settings()
        vectors_dir = Path(settings.DATA_DIR).expanduser() / "vectors"
        vectors_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(vectors_dir))
        logger.info("LanceDB connected at %s", vectors_dir)

    def _get_table(self) -> Any:
        self._connect()
        existing = self._db.list_tables().tables
        if TABLE_NAME in existing:
            return self._db.open_table(TABLE_NAME)
        return self._db.create_table(TABLE_NAME, schema=SCHEMA)

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """Upsert chunk rows keyed on chunk_id."""
        if not chunks:
            return
        table = self._get_table()
        table.merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(
            chunks
        )
        logger.info("Upserted %d chunks to LanceDB", len(chunks))

    def delete_document(self, document_id: str) -> None:
        """Delete all vectors for the given document_id."""
        table = self._get_table()
        table.delete(f"document_id = '{document_id}'")
        logger.info("Deleted vectors for document %s from LanceDB", document_id)


_lancedb_service: LanceDBService | None = None


def get_lancedb_service() -> LanceDBService:
    global _lancedb_service
    if _lancedb_service is None:
        _lancedb_service = LanceDBService()
    return _lancedb_service
