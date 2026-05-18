"""Pure helpers extracted from `app/routers/notes.py`.

These cover FTS5 row sync, tag/source pivot sync, embedding + graph
fire-and-forget upserts, and the `NoteResponse` builder. The router
re-exports them under their original `_`-prefixed aliases via `__all__`
so `routers/tags.py` (which imports `_sync_tag_index`) and tests keep
working.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import NoteModel, NoteSourceModel, NoteTagIndexModel
from app.schemas.notes import NoteResponse
from app.services import embedder as _embedder_module  # indirect: get_embedding_service is patched
from app.services import (
    note_graph as _note_graph_module,  # indirect: get_note_graph_service is patched
)
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)
from app.services.naming import normalize_tag_slug
from app.services.tag_graph import invalidate_tag_graph_cache

logger = logging.getLogger(__name__)


def to_response(
    note: NoteModel,
    collection_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        document_id=note.document_id,
        chunk_id=note.chunk_id,
        section_id=note.section_id,
        content=note.content,
        tags=note.tags or [],
        group_name=note.group_name,
        collection_ids=collection_ids or [],
        source_document_ids=source_document_ids or [],
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def fts_insert(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await session.execute(
        text("INSERT INTO notes_fts(note_id, content, document_id) VALUES (:nid, :content, :doc)"),
        {"nid": note_id, "content": content, "doc": document_id or ""},
    )


async def fts_delete(note_id: str, session: AsyncSession) -> None:
    """Delete rows from the FTS5 virtual table for a given note_id.

    Note_id is UNINDEXED. We find the rowid(s) from the virtual table itself
    and delete by rowid for maximum compatibility.
    """
    await session.execute(
        text(
            "DELETE FROM notes_fts WHERE rowid IN "
            "(SELECT rowid FROM notes_fts WHERE note_id = :nid)"
        ),
        {"nid": note_id},
    )


async def fts_update(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await fts_delete(note_id, session)
    await fts_insert(note_id, content, document_id, session)


async def sync_tag_index(note_id: str, tags: list[str], session: AsyncSession) -> None:
    """Sync NoteTagIndexModel and CanonicalTagModel for a note.

    Called synchronously within the same DB write transaction as the note.
    Handles create (empty -> new tags), update (old -> new tags), and delete
    (call with tags=[] to remove all rows for this note).
    """

    tags = [normalize_tag_slug(t) for t in tags if normalize_tag_slug(t)]

    old_rows = (
        (
            await session.execute(
                select(NoteTagIndexModel.tag_full).where(NoteTagIndexModel.note_id == note_id)
            )
        )
        .scalars()
        .all()
    )
    old_tags: set[str] = set(old_rows)
    new_tags: set[str] = set(tags)

    removed = old_tags - new_tags
    added = new_tags - old_tags

    for tag in removed:
        await session.execute(
            delete(NoteTagIndexModel).where(
                NoteTagIndexModel.note_id == note_id,
                NoteTagIndexModel.tag_full == tag,
            )
        )
        await session.execute(
            text("UPDATE canonical_tags SET note_count = MAX(0, note_count - 1) WHERE id = :tag"),
            {"tag": tag},
        )

    for tag in added:
        segments = tag.split("/")
        tag_root = segments[0]
        tag_parent = "/".join(segments[:-1]) if len(segments) > 1 else ""
        display_name = segments[-1]
        canonical_parent = tag_parent if tag_parent else None

        await session.execute(
            text(
                "INSERT OR IGNORE INTO note_tag_index"
                " (note_id, tag_full, tag_root, tag_parent)"
                " VALUES (:note_id, :tag_full, :tag_root, :tag_parent)"
            ),
            {
                "note_id": note_id,
                "tag_full": tag,
                "tag_root": tag_root,
                "tag_parent": tag_parent,
            },
        )
        await session.execute(
            text(
                "INSERT INTO canonical_tags"
                " (id, display_name, parent_tag, note_count, created_at)"
                " VALUES (:id, :display_name, :parent_tag, 1, datetime('now'))"
                " ON CONFLICT(id) DO UPDATE SET"
                " note_count = canonical_tags.note_count + 1"
            ),
            {
                "id": tag,
                "display_name": display_name,
                "parent_tag": canonical_parent,
            },
        )

    # Invalidate tag graph cache when tag index changes
    if removed or added:

        invalidate_tag_graph_cache()


async def sync_note_sources(
    note_id: str, source_document_ids: list[str], session: AsyncSession
) -> None:
    """Sync NoteSourceModel rows for a note

    Deletes rows not in new list; inserts new rows via INSERT OR IGNORE (idempotent).
    """
    if source_document_ids:
        await session.execute(
            delete(NoteSourceModel).where(
                NoteSourceModel.note_id == note_id,
                NoteSourceModel.document_id.not_in(source_document_ids),
            )
        )
        for doc_id in source_document_ids:
            await session.execute(
                text(
                    "INSERT OR IGNORE INTO note_sources (note_id, document_id, added_at)"
                    " VALUES (:note_id, :document_id, :added_at)"
                ),
                {
                    "note_id": note_id,
                    "document_id": doc_id,
                    "added_at": datetime.now(UTC).isoformat(),
                },
            )
    else:
        await session.execute(delete(NoteSourceModel).where(NoteSourceModel.note_id == note_id))


async def upsert_note_graph(
    note_id: str,
    content: str,
    document_id: str | None,
    tags: list[str],
    source_document_ids: list[str] | None = None,
) -> None:
    """Fire-and-forget: upsert Note node and edges in Kuzu graph."""
    try:

        await _note_graph_module.get_note_graph_service().upsert_note_node(
            note_id, content, document_id, tags, source_document_ids or []
        )
        logger.debug("Note graph upserted note_id=%s", note_id)
    except Exception as exc:
        logger.warning("upsert_note_graph failed (non-fatal): %s", exc)


async def embed_and_store_note(note_id: str, content: str, document_id: str | None) -> None:
    """Embed note content and upsert vector. Non-fatal if embedding model unavailable.

    Checks the note's current content before upserting to avoid overwriting a
    newer embedding with a stale one (race between create and rapid update).
    """
    try:

        loop = asyncio.get_event_loop()
        embedder = _embedder_module.get_embedding_service()
        vector = await loop.run_in_executor(None, lambda: embedder.encode([content])[0])

        async with get_session_factory()() as session:
            row = (
                await session.execute(select(NoteModel.content).where(NoteModel.id == note_id))
            ).scalar_one_or_none()
        if row is None:
            logger.debug("Note %s deleted before embedding completed, skipping", note_id)
            return
        if row != content:
            logger.debug("Note %s content changed, skipping stale embedding", note_id)
            return

        lancedb = _vector_store_module.get_lancedb_service()
        lancedb.upsert_note_vector(note_id, document_id, content, vector)
        logger.debug("Note vector stored note_id=%s", note_id)
    except Exception as exc:
        logger.warning("embed_and_store_note failed (non-fatal): %s", exc)
