import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa

from app.config import get_settings

logger = logging.getLogger(__name__)

# The one embedding space. Notes, chunks, concepts and images are all written by
# the deployed embedder (bge-small-en-v1.5, 384-dim) and compared against each
# other, so every table in that space declares this and nothing declares its own
# number -- I-9. `note_vectors_v2` carried a hand-written 1024 for long enough
# that not one of a 61-note library was ever embedded: a 384-float list cannot be
# cast into a 1024 fixed-size list, every write raised, and
# `embed_and_store_note` logged it as non-fatal and moved on.
EMBEDDING_DIM = 384

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
        pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    ]
)

NOTE_TABLE_NAME = "note_vectors_v2"
NOTE_VECTOR_DIM = EMBEDDING_DIM

NOTE_SCHEMA = pa.schema(
    [
        pa.field("note_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("content", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), NOTE_VECTOR_DIM)),
    ]
)

IMAGE_TABLE_NAME = "image_vectors_v1"
# LanceDB predicates are built by string interpolation, so ids that reach one are
# shape-checked first. Every image id is a uuid4 this process generated.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# LanceDB takes predicates as SQL strings and offers no parameter binding, so a
# quoted id is the only way to filter and shape-checking is the only defence.
# Both forms are real: `uuid.uuid4()` for documents, chunks, notes and images,
# and `uuid.uuid4().hex` for concepts and study events. Accepting only the dashed
# form would silently make every concept-vector predicate match nothing.
_SAFE_ID_RE = re.compile(r"[0-9a-fA-F]{32}|" + _UUID_RE.pattern)

IMAGE_SCHEMA = pa.schema(
    [
        pa.field("image_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("description", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    ]
)

# Concept vectors live in CHUNK space (bge-small-en-v1.5, 384-dim), because a concept's
# default vector is the centroid of its evidence-chunk vectors -- a free mean over vectors
# that already exist. This keeps concepts directly comparable to chunks and to bge-small
# query embeddings (scope resolution, concept dedup). It is a DERIVED projection, never a
# retrieval primary (see docs/concepts.md, invariant I-20).
CONCEPT_TABLE_NAME = "concept_vectors_v1"
CONCEPT_VECTOR_DIM = EMBEDDING_DIM

CONCEPT_SCHEMA = pa.schema(
    [
        pa.field("concept_id", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), CONCEPT_VECTOR_DIM)),
    ]
)


def safe_id(value: str) -> str | None:
    """*value* if it is an id this process generates, else None."""
    return value if value and _SAFE_ID_RE.fullmatch(value) else None


def id_predicate(column: str, ids: Sequence[str], *, context: str) -> str | None:
    """`column IN ('a','b')` over the ids that pass the shape check.

    None when nothing survives, which callers must treat as "match nothing"
    rather than falling through to an unfiltered predicate -- an `IN ()` that
    silently became `WHERE true` would delete a whole table.
    """
    kept = [i for i in ids if safe_id(i)]
    if len(kept) != len(ids):
        logger.warning(
            "%s: refused %d id(s) that are not the shape this process generates",
            context,
            len(ids) - len(kept),
        )
    if not kept:
        return None
    return f"{column} IN ({', '.join(chr(39) + i + chr(39) for i in kept)})"


def eq_predicate(column: str, value: str, *, context: str) -> str | None:
    """`column = 'value'`, or None when the id fails the shape check."""
    if safe_id(value) is None:
        logger.warning("%s: refused an id that is not the shape this process generates", context)
        return None
    return f"{column} = '{value}'"


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
            pred = eq_predicate("document_id", document_id, context="count_for_document")
            return table.count_rows(pred) if pred else 0
        except Exception:
            logger.warning("row count failed for %s; reporting 0", document_id, exc_info=True)
            return 0

    def delete_document(self, document_id: str) -> None:
        """Delete all vectors for the given document_id."""
        pred = eq_predicate("document_id", document_id, context="delete_document")
        if pred is None:
            return
        table = self._get_table()
        table.delete(pred)
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
        try:
            return self._db.create_table(NOTE_TABLE_NAME, schema=NOTE_SCHEMA)
        except ValueError:
            # list_tables() then create_table() is check-then-act, and two
            # concurrent callers both pass the check. Reachable without any test
            # harness: `POST /notes` schedules its embedding as a background
            # task, so creating two notes in quick succession on a fresh install
            # races here and one of them raises "Table already exists".
            return self._db.open_table(NOTE_TABLE_NAME)

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
        """Delete the vector for the given note_id.

        Non-fatal on purpose: a vector-store hiccup must not fail the user's
        `DELETE /notes/{id}`, which has already removed the note itself. What
        makes that safe is `NoteSearchService._drop_deleted` -- the semantic arm
        resolves every hit against `notes`, so a row this call failed to remove
        is invisible rather than served as a live note. Before that join existed,
        one swallowed exception here kept a deleted note searchable forever.

        Logged with the traceback, not just a message: a silent counter of
        "deletes that did not happen" is how the ghost went unnoticed.
        """
        try:
            pred = eq_predicate("note_id", note_id, context="delete_note_vector")
            if pred is None:
                return
            table = self._get_or_create_note_table()
            table.delete(pred)
            logger.debug("Deleted note vector note_id=%s", note_id)
        except Exception:
            logger.exception("delete_note_vector failed for note_id=%s", note_id)

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
                # No usable id means "match nothing". Skipping the filter would
                # widen an explicitly scoped search to the whole library.
                pred = id_predicate("document_id", document_ids, context="search_image_vectors")
                if pred is None:
                    return []
                search = search.where(pred, prefilter=True)
            rows = search.to_list()
            return [row for row in rows if 1.0 - float(row.get("_distance", 1.0)) >= threshold]
        except Exception as exc:
            logger.warning("search_image_vectors failed: %s", exc)
            return []

    def delete_image_vectors_for_document(self, document_id: str) -> None:
        """Delete all image vectors for the given document_id."""
        try:
            pred = eq_predicate(
                "document_id", document_id, context="delete_image_vectors_for_document"
            )
            if pred is None:
                return
            table = self._get_image_table()
            table.delete(pred)
            logger.info("Deleted image vectors for document %s", document_id)
        except Exception as exc:
            logger.warning("delete_image_vectors_for_document failed doc=%s: %s", document_id, exc)

    def delete_image_vectors(self, image_ids: list[str]) -> None:
        """Delete specific image vectors by id.

        Used when re-extraction retires a figure that the current extractor no
        longer produces: the document keeps its other images, so the
        document-wide delete above is the wrong tool. Ids are UUIDs generated by
        this process, but they are quoted into a predicate, so anything that is
        not one is refused rather than interpolated.
        """
        if not image_ids:
            return
        safe = [i for i in image_ids if _UUID_RE.fullmatch(i)]
        if len(safe) != len(image_ids):
            logger.warning(
                "delete_image_vectors: refused %d id(s) that are not UUIDs",
                len(image_ids) - len(safe),
            )
        if not safe:
            return
        try:
            pred = id_predicate("image_id", safe, context="delete_image_vectors")
            if pred is None:
                return
            table = self._get_image_table()
            table.delete(pred)
            logger.info("Deleted %d image vector(s)", len(safe))
        except Exception as exc:
            logger.warning("delete_image_vectors failed: %s", exc)

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
                pred = id_predicate("chunk_id", batch, context="vectors_for_chunks")
                if pred is None:
                    continue
                rows = (
                    table.search()
                    .where(pred)
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

            # None, not []: the caller writes the centroid when it is not None,
            # and an empty vector reaches LanceDB as a zero-length list, which
            # fails the fixed-size schema at write time rather than here.
            pred = id_predicate("chunk_id", chunk_ids, context="compute_centroid")
            if pred is None:
                return None
            table = self._get_table()
            # search() with no query vector is a plain filtered scan; limit must be
            # explicit (default is 10) so we don't truncate the evidence set.
            rows = (
                table.search()
                .where(pred)
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
            pred = eq_predicate("concept_id", concept_id, context="delete_concept_vector")
            if pred is None:
                return
            table = self._get_or_create_concept_table()
            table.delete(pred)
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
