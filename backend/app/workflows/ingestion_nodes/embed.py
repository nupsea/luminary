"""embed_node + keyword_index_node.

embed_node walks the document in 1000-chunk batches, encoding each batch's
`text` (concatenated with the entity tail when present) via the embedder
service and upserting that batch's vectors into LanceDB before moving on, so
peak memory is a batch rather than a document. CPU-bound encoding runs in a
thread pool so the event loop stays free for status polling.

keyword_index_node populates the SQLite FTS5 mirror table from the
just-written ChunkModel rows. text || entities_text so BM25 matches
canonical entity names.
"""

import asyncio
import logging

from app.database import get_session_factory
from app.repos.document_repo import index_chunks_fts
from app.telemetry import trace_ingestion_node
from app.workflows.ingestion_nodes._shared import IngestionState, _update_stage

logger = logging.getLogger(__name__)


class VectorCountMismatch(Exception):
    """LanceDB holds fewer vectors than the document has chunks. The graph retries embed once."""


async def embed_node(state: IngestionState) -> IngestionState:

    logger.debug("node_start", extra={"node": "embed", "doc_id": state["document_id"]})
    with trace_ingestion_node("embed", state):
        doc_id = state["document_id"]
        chunks = state.get("chunks") or []
        if not chunks:
            logger.warning("embed_node: no chunks to embed", extra={"doc_id": doc_id})
            await _update_stage(doc_id, "embedding")
            return {**state, "status": "indexing"}

        from app.services.embedder import chunk_embedding_text, get_embedding_service
        from app.services.vector_store import get_lancedb_service

        embedder = get_embedding_service()

        # Update stage BEFORE encoding so UI reflects current work immediately
        await _update_stage(doc_id, "embedding")
        logger.info(
            "Embedding started",
            extra={"doc_id": doc_id, "num_chunks": len(chunks)},
        )

        # A batch is the unit of work, not a document: peak memory is one batch's
        # text and vectors, whatever the document's size. Encoding is per-text, so
        # batching leaves every vector bitwise identical.
        batch_size = 1000
        lancedb_svc = get_lancedb_service()
        loop = asyncio.get_event_loop()
        for start_idx in range(0, len(chunks), batch_size):
            batch_chunks = chunks[start_idx : start_idx + batch_size]
            # Display text remains in chunk["text"].
            texts = [chunk_embedding_text(c["text"], c.get("entities_text")) for c in batch_chunks]
            # CPU-bound encoding in a thread pool so the event loop stays free
            # for status poll requests during the (potentially long) pass.
            embeddings = await loop.run_in_executor(None, embedder.encode, texts)
            rows = [
                {
                    "chunk_id": c["id"],
                    "document_id": doc_id,
                    "section_heading": "",
                    "page": 0,
                    "chunk_index": c.get("index", 0),
                    "speaker": "",
                    "text": c["text"],
                    "vector": embeddings[i],
                }
                for i, c in enumerate(batch_chunks)
            ]
            # Batched so LanceDB/DataFusion never spills on a 9400-chunk document;
            # synchronous, so off the loop (I-2).
            await asyncio.to_thread(lancedb_svc.upsert_chunks, rows)
            logger.info(
                "Upserted batch %d-%d to LanceDB",
                start_idx,
                min(start_idx + batch_size, len(chunks)),
            )
            # Explicit: the next batch's encode allocates before CPython would
            # otherwise drop these, so the peak would still hold two batches.
            del texts, embeddings, rows

        # A silent LanceDB write failure (LanceDB is single-writer) must never leave
        # a document complete with missing vectors. Upserts are keyed by chunk id,
        # so the retry rewrites the whole document safely.
        written = await asyncio.to_thread(lancedb_svc.count_for_document, doc_id)
        if written != len(chunks):
            raise VectorCountMismatch(f"vector count {written} != chunk count {len(chunks)}")

        logger.info("Embedded %d chunks", len(chunks), extra={"doc_id": doc_id})
        return {**state, "status": "indexing"}


async def keyword_index_node(state: IngestionState) -> IngestionState:

    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "keyword_index", "doc_id": doc_id})
    with trace_ingestion_node("keyword_index", state):
        try:
            async with get_session_factory()() as session:
                await index_chunks_fts(session, doc_id)
                await session.commit()
            logger.info("FTS5 index populated", extra={"doc_id": doc_id})
            # Forward-fill per-chunk content dates for temporal query filters.
            # Non-fatal: a date-parse hiccup must not fail indexing.
            try:
                from app.services.content_dates import assign_entry_dates

                async with get_session_factory()() as session:
                    dated = await assign_entry_dates(session, doc_id)
                    await session.commit()
                if dated:
                    logger.info("dated %d chunks", dated, extra={"doc_id": doc_id})
            except Exception as exc:
                logger.warning("entry_date assignment failed (non-fatal): %s", exc)
        except Exception as exc:
            logger.exception("keyword_index_node failed", exc_info=exc)
        await _update_stage(doc_id, "indexing")
    return {**state, "status": "extracting"}
