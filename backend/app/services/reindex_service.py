"""ReindexService: backfill missing note embeddings in LanceDB.

Identifies notes whose note_id is absent from note_vectors_v2 and re-embeds them.
All LanceDB calls are synchronous and wrapped in asyncio.to_thread per I-2.
"""

import asyncio
import logging
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteModel

logger = logging.getLogger(__name__)


class ReindexReport(TypedDict):
    total: int
    reindexed: int
    failed: int


class ReindexService:
    async def reindex_notes(self, db: AsyncSession) -> ReindexReport:
        """Fetch all notes; re-embed those absent from LanceDB.

        LanceDB calls are wrapped in asyncio.to_thread (I-2).
        Exceptions per note are caught and counted in `failed`.
        """
        from app.services.embedder import get_embedding_service  # noqa: PLC0415
        from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

        result = await db.execute(select(NoteModel.id, NoteModel.content, NoteModel.document_id))
        rows = result.all()
        total = len(rows)
        reindexed = 0
        failed = 0

        svc = get_lancedb_service()
        embedder = get_embedding_service()

        for note_id, content, document_id in rows:
            try:
                # Check presence in LanceDB (synchronous call wrapped in thread)
                def _check_present(nid: str = note_id) -> bool:
                    tbl = svc._get_or_create_note_table()
                    # Use count_rows with filter for presence check
                    try:
                        count = tbl.count_rows(f"note_id = '{nid}'")
                        return count > 0
                    except Exception:
                        return False

                present = await asyncio.to_thread(_check_present)
                if present:
                    continue

                # Embed and upsert (synchronous embedding + LanceDB wrapped together)
                def _embed_and_upsert(
                    nid: str = note_id,
                    c: str = content,
                    doc_id: str | None = document_id,
                ) -> None:
                    vector = embedder.encode([c])[0]
                    svc.upsert_note_vector(nid, doc_id, c, vector)

                await asyncio.to_thread(_embed_and_upsert)
                reindexed += 1
                logger.info("Reindexed note_id=%s", note_id)

            except Exception as exc:
                logger.warning("reindex_notes: failed for note_id=%s: %s", note_id, exc)
                failed += 1

        logger.info(
            "reindex_notes complete: total=%d reindexed=%d failed=%d",
            total,
            reindexed,
            failed,
        )
        return ReindexReport(total=total, reindexed=reindexed, failed=failed)


_reindex_service: ReindexService | None = None


def get_reindex_service() -> ReindexService:
    global _reindex_service
    if _reindex_service is None:
        _reindex_service = ReindexService()
    return _reindex_service
