"""S224: reindex chunk entity tails (entities_text column) for a document or
all documents.

Re-runs GLiNER + EntityDisambiguator over a document's existing chunks, rebuilds
the deterministic canonical entity tail via build_entity_tail(), and writes it
back to chunks.entities_text. Then re-embeds the (text + entity tail) for
LanceDB and rebuilds the chunks_fts row using the concatenated text.

Idempotent: every run overwrites entities_text and replaces the LanceDB / FTS5
row, never appends. Safe to run repeatedly.

CLI:
    cd backend && uv run python -m app.scripts.reindex_entities --document-id <id>
    cd backend && uv run python -m app.scripts.reindex_entities --all

Per I-1: uses a single AsyncSession (no asyncio.gather with shared session).
Per I-2: every LanceDB upsert wrapped in asyncio.to_thread.
Per I-4: chunks_fts row deletion uses rowid-based DELETE (always reliable).
Per I-16: GLiNER + Kuzu are local; no external API calls.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select, text
from sqlalchemy import update as sa_update

from app.database import get_session_factory
from app.models import ChunkModel, DocumentModel
from app.workflows.ingestion import build_entity_tail

logger = logging.getLogger(__name__)


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    if pct <= 0:
        return s[0]
    if pct >= 100:
        return s[-1]
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return int(round(s[lo] * (1 - frac) + s[hi] * frac))


async def _list_document_ids() -> list[str]:
    async with get_session_factory()() as session:
        result = await session.execute(select(DocumentModel.id))
        return [row[0] for row in result.all()]


async def reindex_document(doc_id: str) -> dict[str, int]:
    """Reindex one document's chunk entity tails. Returns metrics dict."""
    from app.services.embedder import get_embedding_service
    from app.services.entity_disambiguator import canonicalize_batch
    from app.services.graph import get_graph_service
    from app.services.ner import get_entity_extractor
    from app.services.vector_store import get_lancedb_service

    metrics = {
        "chunks_updated": 0,
        "entities_injected_total": 0,
        "p95_entities_per_chunk": 0,
    }

    async with get_session_factory()() as session:
        doc_row = (
            await session.execute(
                select(DocumentModel.title, DocumentModel.content_type).where(
                    DocumentModel.id == doc_id
                )
            )
        ).first()
        if doc_row is None:
            logger.warning("reindex_entities: doc_id not found", extra={"doc_id": doc_id})
            return metrics
        content_type = doc_row.content_type or "notes"

        chunk_rows = (
            await session.execute(
                select(ChunkModel.id, ChunkModel.text).where(
                    ChunkModel.document_id == doc_id
                )
            )
        ).all()
        if not chunk_rows:
            logger.info("reindex_entities: no chunks", extra={"doc_id": doc_id})
            return metrics

        chunk_dicts = [
            {"id": row.id, "document_id": doc_id, "text": row.text} for row in chunk_rows
        ]

        # NER -- CPU bound, run in thread pool. Reuse the cached extractor.
        extractor = get_entity_extractor()
        loop = asyncio.get_event_loop()
        entities = await loop.run_in_executor(
            None, extractor.extract, chunk_dicts, content_type
        )

        # Best-effort Kuzu lookup. If Kuzu is locked by another process (e.g. the
        # live backend holds it), fall back to empty existing_by_type -- the
        # canonicalizer still converges within the batch via Pass 1 / Pass 2.
        existing_by_type: dict[str, list[str]]
        try:
            graph = get_graph_service()
            existing_by_type = graph.get_entities_by_type_for_document(doc_id)
        except Exception as exc:  # pragma: no cover -- defensive concurrency guard
            logger.warning(
                "reindex_entities: Kuzu unavailable, using empty canonical pool",
                extra={"doc_id": doc_id, "error": repr(exc)},
            )
            existing_by_type = {}
        canonical_triples = canonicalize_batch(
            [(ent["name"], ent["type"]) for ent in entities],
            existing_by_type,
        )

        chunk_to_entities: dict[str, set[str]] = {}
        for (canonical, _etype, _original), ent in zip(canonical_triples, entities):
            chunk_to_entities.setdefault(ent["chunk_id"], set()).add(canonical)

        per_chunk_counts: list[int] = []
        for chunk in chunk_dicts:
            cid = chunk["id"]
            canonicals = chunk_to_entities.get(cid)
            tail = build_entity_tail(canonicals) if canonicals else ""
            chunk["entities_text"] = tail or None
            await session.execute(
                sa_update(ChunkModel)
                .where(ChunkModel.id == cid)
                .values(entities_text=tail or None)
            )
            if canonicals:
                metrics["chunks_updated"] += 1
                metrics["entities_injected_total"] += len(canonicals)
                per_chunk_counts.append(len(canonicals))

        await session.commit()

        # Re-embed using concatenated text; upsert to LanceDB (per I-2 in thread).
        embedder = get_embedding_service()
        texts_for_embedding = [
            c["text"] + ("\n" + c["entities_text"] if c.get("entities_text") else "")
            for c in chunk_dicts
        ]
        embeddings = await loop.run_in_executor(None, embedder.encode, texts_for_embedding)
        lancedb_rows = [
            {
                "chunk_id": c["id"],
                "document_id": doc_id,
                "content_type": content_type,
                "section_heading": "",
                "page": 0,
                "chunk_index": idx,
                "speaker": "",
                "text": c["text"],
                "vector": embeddings[idx],
            }
            for idx, c in enumerate(chunk_dicts)
        ]
        lancedb_svc = get_lancedb_service()
        batch_size = 1000
        for start in range(0, len(lancedb_rows), batch_size):
            batch = lancedb_rows[start : start + batch_size]
            await asyncio.to_thread(lancedb_svc.upsert_chunks, batch)

        # Rebuild FTS5 rows (rowid-based delete + reinsert with concatenated text).
        # I-4: rowid-based delete is always reliable for FTS5 with UNINDEXED cols.
        await session.execute(
            text(
                "DELETE FROM chunks_fts WHERE rowid IN ("
                "  SELECT rowid FROM chunks WHERE document_id = :doc_id"
                ")"
            ),
            {"doc_id": doc_id},
        )
        await session.execute(
            text(
                "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                "SELECT rowid, "
                "       text || CASE "
                "         WHEN entities_text IS NOT NULL AND entities_text != '' "
                "         THEN ' ' || entities_text "
                "         ELSE '' END, "
                "       id, document_id FROM chunks "
                "WHERE document_id = :doc_id"
            ),
            {"doc_id": doc_id},
        )
        await session.commit()

    metrics["p95_entities_per_chunk"] = _percentile(per_chunk_counts, 95)
    logger.info(
        "reindex_entities completed",
        extra={
            "doc_id": doc_id,
            "chunks_updated": metrics["chunks_updated"],
            "entities_injected_total": metrics["entities_injected_total"],
            "p95_entities_per_chunk": metrics["p95_entities_per_chunk"],
        },
    )
    return metrics


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.all:
        doc_ids = await _list_document_ids()
        if not doc_ids:
            logger.warning("reindex_entities --all: no documents found")
            return 0
    else:
        doc_ids = [args.document_id]

    for doc_id in doc_ids:
        try:
            await reindex_document(doc_id)
        except Exception:
            logger.exception("reindex_entities failed", extra={"doc_id": doc_id})
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.scripts.reindex_entities",
        description="S224: rebuild entities_text + LanceDB + FTS5 for a document.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--document-id", dest="document_id", help="Reindex a single document by id")
    group.add_argument(
        "--all", action="store_true", help="Reindex every document in the catalog"
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
