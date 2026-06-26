import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

from app.config import get_settings

logger = logging.getLogger(__name__)

TABLE_NAME = "chunk_vectors_v3"

SCHEMA = pa.schema(
    [
        pa.field("chunk_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("content_type", pa.string()),
        pa.field("section_heading", pa.string()),
        pa.field("page", pa.int32()),
        pa.field("chunk_index", pa.int32()),
        pa.field("speaker", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 384)),
    ]
)

NOTE_TABLE_NAME = "note_vectors_v2"
NOTE_VECTOR_DIM = 1024

NOTE_SCHEMA = pa.schema(
    [
        pa.field("note_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("content", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), NOTE_VECTOR_DIM)),
    ]
)

IMAGE_TABLE_NAME = "image_vectors_v1"

IMAGE_SCHEMA = pa.schema(
    [
        pa.field("image_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("description", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 384)),
    ]
)

# Concept vectors live in CHUNK space (bge-small-en-v1.5, 384-dim), because a concept's
# default vector is the centroid of its evidence-chunk vectors -- a free mean over vectors
# that already exist. This keeps concepts directly comparable to chunks and to bge-small
# query embeddings (scope resolution, concept dedup). It is a DERIVED projection, never a
# retrieval primary (see docs/concepts.md, invariant I-20).
CONCEPT_TABLE_NAME = "concept_vectors_v1"
CONCEPT_VECTOR_DIM = 384  # chunk/bge-small space -- matches chunk_vectors_v3

CONCEPT_SCHEMA = pa.schema(
    [
        pa.field("concept_id", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), CONCEPT_VECTOR_DIM)),
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
        table.merge_insert(
            "chunk_id"
        ).when_matched_update_all().when_not_matched_insert_all().execute(chunks)
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

    def _get_or_create_note_table(self) -> Any:
        self._connect()
        existing = self._db.list_tables().tables
        if NOTE_TABLE_NAME in existing:
            tbl = self._db.open_table(NOTE_TABLE_NAME)
            # Inspect the vector field dimension; drop and recreate if mismatched
            try:
                vector_field = tbl.schema.field("vector")
                actual_dim = vector_field.type.list_size
                if actual_dim != NOTE_VECTOR_DIM:
                    logger.warning(
                        "note_vectors_v2 schema mismatch (found %d-dim) -- dropping and "
                        "recreating with %d-dim",
                        actual_dim,
                        NOTE_VECTOR_DIM,
                    )
                    self._db.drop_table(NOTE_TABLE_NAME)
                    return self._db.create_table(NOTE_TABLE_NAME, schema=NOTE_SCHEMA)
            except Exception as exc:
                logger.warning("Could not inspect note_vectors_v2 schema: %s", exc)
            return tbl
        return self._db.create_table(NOTE_TABLE_NAME, schema=NOTE_SCHEMA)

    def upsert_note_vector(
        self, note_id: str, document_id: str | None, content: str, vector: list[float]
    ) -> None:
        """Upsert a single note embedding keyed on note_id."""
        table = self._get_or_create_note_table()
        table.merge_insert(
            "note_id"
        ).when_matched_update_all().when_not_matched_insert_all().execute(
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
            table = self._get_or_create_note_table()
            table.delete(f"note_id = '{note_id}'")
            logger.debug("Deleted note vector note_id=%s", note_id)
        except Exception as exc:
            logger.warning("delete_note_vector failed for note_id=%s: %s", note_id, exc)

    def _get_image_table(self) -> Any:
        self._connect()
        existing = self._db.list_tables().tables
        if IMAGE_TABLE_NAME in existing:
            return self._db.open_table(IMAGE_TABLE_NAME)
        return self._db.create_table(IMAGE_TABLE_NAME, schema=IMAGE_SCHEMA)

    def upsert_image_vector(
        self, image_id: str, document_id: str, description: str, vector: list[float]
    ) -> None:
        """Upsert a single image description embedding keyed on image_id."""
        table = self._get_image_table()
        table.merge_insert(
            "image_id"
        ).when_matched_update_all().when_not_matched_insert_all().execute(
            [
                {
                    "image_id": image_id,
                    "document_id": document_id,
                    "description": description,
                    "vector": vector,
                }
            ]
        )
        logger.debug("Upserted image vector image_id=%s", image_id)

    def search_image_vectors(
        self,
        query_vector: list[float],
        document_ids: list[str] | None,
        k: int = 5,
        threshold: float = 0.5,
    ) -> list[dict]:
        """Cosine search image_vectors; returns rows where similarity >= threshold."""
        try:
            table = self._get_image_table()
            search = table.search(query_vector).metric("cosine").limit(k)
            if document_ids:
                id_list = ", ".join(f"'{did}'" for did in document_ids)
                search = search.where(f"document_id IN ({id_list})", prefilter=True)
            rows = search.to_list()
            return [row for row in rows if 1.0 - float(row.get("_distance", 1.0)) >= threshold]
        except Exception as exc:
            logger.warning("search_image_vectors failed: %s", exc)
            return []

    def delete_image_vectors_for_document(self, document_id: str) -> None:
        """Delete all image vectors for the given document_id."""
        try:
            table = self._get_image_table()
            table.delete(f"document_id = '{document_id}'")
            logger.info("Deleted image vectors for document %s", document_id)
        except Exception as exc:
            logger.warning("delete_image_vectors_for_document failed doc=%s: %s", document_id, exc)

    # --- Concept vectors (derived centroid; see docs/concepts.md) ---
    # NOTE: all methods here are synchronous LanceDB calls. Callers MUST wrap them in
    # asyncio.to_thread when invoked from async code (invariant I-2).

    def _get_or_create_concept_table(self) -> Any:
        self._connect()
        existing = self._db.list_tables().tables
        if CONCEPT_TABLE_NAME in existing:
            return self._db.open_table(CONCEPT_TABLE_NAME)
        return self._db.create_table(CONCEPT_TABLE_NAME, schema=CONCEPT_SCHEMA)

    def fetch_chunk_vectors(self, chunk_ids: list[str]) -> dict[str, list[float]]:
        """Bulk-load chunk_id -> vector for the given ids (one filtered scan).

        Used to build context-centroid embeddings for concepts without a per-entity
        LanceDB query. Returns {} on any error.
        """
        if not chunk_ids:
            return {}
        try:
            table = self._get_table()
            out: dict[str, list[float]] = {}
            # chunk in batches to keep the IN(...) filter a sane size
            ids = list(dict.fromkeys(chunk_ids))
            for i in range(0, len(ids), 800):
                batch = ids[i : i + 800]
                id_list = ", ".join(f"'{c}'" for c in batch)
                rows = (
                    table.search()
                    .where(f"chunk_id IN ({id_list})")
                    .select(["chunk_id", "vector"])
                    .limit(len(batch))
                    .to_list()
                )
                for r in rows:
                    if r.get("vector") is not None:
                        out[r["chunk_id"]] = r["vector"]
            return out
        except Exception as exc:
            logger.warning("fetch_chunk_vectors failed: %s", exc)
            return {}

    def compute_centroid(self, chunk_ids: list[str]) -> list[float] | None:
        """Mean of the evidence chunks' vectors (chunk space, 384-dim).

        Returns None when none of the chunk_ids have a stored vector. This is the
        free, always-on concept vector: no new embedding calls.
        """
        if not chunk_ids:
            return None
        try:
            import numpy as np  # noqa: PLC0415

            table = self._get_table()
            id_list = ", ".join(f"'{cid}'" for cid in chunk_ids)
            # search() with no query vector is a plain filtered scan; limit must be
            # explicit (default is 10) so we don't truncate the evidence set.
            rows = (
                table.search()
                .where(f"chunk_id IN ({id_list})")
                .select(["vector"])
                .limit(len(chunk_ids))
                .to_list()
            )
            vectors = [r["vector"] for r in rows if r.get("vector") is not None]
            if not vectors:
                return None
            centroid = np.mean(np.array(vectors, dtype="float32"), axis=0)
            return centroid.astype("float32").tolist()
        except Exception as exc:
            logger.warning("compute_centroid failed for %d chunks: %s", len(chunk_ids), exc)
            return None

    def upsert_concept_vector(self, concept_id: str, vector: list[float]) -> None:
        """Upsert a single concept vector keyed on concept_id."""
        table = self._get_or_create_concept_table()
        table.merge_insert(
            "concept_id"
        ).when_matched_update_all().when_not_matched_insert_all().execute(
            [{"concept_id": concept_id, "vector": vector}]
        )
        logger.debug("Upserted concept vector concept_id=%s", concept_id)

    def delete_concept_vector(self, concept_id: str) -> None:
        """Delete the vector for the given concept_id."""
        try:
            table = self._get_or_create_concept_table()
            table.delete(f"concept_id = '{concept_id}'")
            logger.debug("Deleted concept vector concept_id=%s", concept_id)
        except Exception as exc:
            logger.warning("delete_concept_vector failed for concept_id=%s: %s", concept_id, exc)

    def clear_concept_vectors(self) -> None:
        """Drop the concept vector table (for a full regenerate). Idempotent."""
        try:
            self._connect()
            if CONCEPT_TABLE_NAME in self._db.list_tables().tables:
                self._db.drop_table(CONCEPT_TABLE_NAME)
        except Exception as exc:
            logger.warning("clear_concept_vectors failed: %s", exc)

    def search_concepts(
        self, query_vector: list[float], k: int = 10, threshold: float = 0.0
    ) -> list[dict]:
        """Cosine search over concept vectors; returns rows with similarity >= threshold.

        Used for concept dedup and scope->concept resolution -- NOT for QA retrieval.
        """
        try:
            table = self._get_or_create_concept_table()
            rows = table.search(query_vector).metric("cosine").limit(k).to_list()
            return [
                {"concept_id": r["concept_id"], "similarity": 1.0 - float(r.get("_distance", 1.0))}
                for r in rows
                if 1.0 - float(r.get("_distance", 1.0)) >= threshold
            ]
        except Exception as exc:
            logger.warning("search_concepts failed: %s", exc)
            return []


_lancedb_service: LanceDBService | None = None


def get_lancedb_service() -> LanceDBService:
    global _lancedb_service
    if _lancedb_service is None:
        _lancedb_service = LanceDBService()
    return _lancedb_service
