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

NOTE_TABLE_NAME = "note_vectors"

NOTE_SCHEMA = pa.schema(
    [
        pa.field("note_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("content", pa.string()),
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

    def count_for_document(self, document_id: str) -> int:
        """Return the number of vector rows stored for the given document_id."""
        try:
            table = self._get_table()
            return table.count_rows(f"document_id = '{document_id}'")
        except Exception:
            return 0

    def delete_document(self, document_id: str) -> None:
        """Delete all vectors for the given document_id."""
        table = self._get_table()
        table.delete(f"document_id = '{document_id}'")
        logger.info("Deleted vectors for document %s from LanceDB", document_id)

    def _get_note_table(self) -> Any:
        self._connect()
        existing = self._db.list_tables().tables
        if NOTE_TABLE_NAME in existing:
            return self._db.open_table(NOTE_TABLE_NAME)
        return self._db.create_table(NOTE_TABLE_NAME, schema=NOTE_SCHEMA)

    def upsert_note_vector(
        self, note_id: str, document_id: str | None, content: str, vector: list[float]
    ) -> None:
        """Upsert a single note embedding keyed on note_id."""
        table = self._get_note_table()
        table.merge_insert("note_id").when_matched_update_all().when_not_matched_insert_all().execute(
            [
                {
                    "note_id": note_id,
                    "document_id": document_id or "",
                    "content": content,
                    "vector": vector,
                }
            ]
        )
        logger.debug("Upserted note vector note_id=%s", note_id)

    def delete_note_vector(self, note_id: str) -> None:
        """Delete the vector for the given note_id."""
        try:
            table = self._get_note_table()
            table.delete(f"note_id = '{note_id}'")
            logger.debug("Deleted note vector note_id=%s", note_id)
        except Exception as exc:
            logger.warning("delete_note_vector failed for note_id=%s: %s", note_id, exc)


_lancedb_service: LanceDBService | None = None


def get_lancedb_service() -> LanceDBService:
    global _lancedb_service
    if _lancedb_service is None:
        _lancedb_service = LanceDBService()
    return _lancedb_service
