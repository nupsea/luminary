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
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import NoteModel
from app.repos.note_repo import NoteRepo
from app.repos.tag_repo import TagRepo
from app.schemas.membership import CollectionRef
from app.schemas.notes import NoteResponse
from app.services import embedder as _embedder_module  # indirect: get_embedding_service is patched
from app.services import (
    note_graph as _note_graph_module,  # indirect: get_note_graph_service is patched
)
from app.services import (
    note_tagger as _note_tagger_module,  # indirect: get_note_tagger is patched
)
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)
from app.services.engagement_service import EngagementService
from app.services.naming import normalize_tag_slug
from app.services.tag_graph import invalidate_tag_graph_cache

logger = logging.getLogger(__name__)


def to_response(
    note: NoteModel,
    collections: list[CollectionRef] | None = None,
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
        collections=collections or [],
        source_document_ids=source_document_ids or [],
        title=note.title,
        title_auto_generated=note.title_auto_generated,
        description=note.description,
        is_favorite=bool(note.is_favorite),
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def fts_insert(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await NoteRepo(session).fts_insert(note_id, content, document_id)


async def fts_delete(note_id: str, session: AsyncSession) -> None:
    await NoteRepo(session).fts_delete(note_id)


async def fts_update(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await fts_delete(note_id, session)
    await fts_insert(note_id, content, document_id, session)


async def _sync_index(
    scope: Literal["note", "document"], member_id: str, tags: list[str], session: AsyncSession
) -> list[str]:
    """Move a member's tag index and canonical usage counts to `tags`; returns them normalised."""
    tags = [normalize_tag_slug(t) for t in tags if normalize_tag_slug(t)]
    repo = TagRepo(session)
    old_tags = await repo.indexed_tags(scope, member_id)
    new_tags = set(tags)
    removed = old_tags - new_tags
    added = new_tags - old_tags
    for tag in removed:
        await repo.unindex(scope, member_id, tag)
    for tag in added:
        await repo.index(scope, member_id, tag)
    if removed or added:
        invalidate_tag_graph_cache()
    return tags


async def sync_tag_index(note_id: str, tags: list[str], session: AsyncSession) -> None:
    """Sync NoteTagIndexModel and CanonicalTagModel for a note.

    Called synchronously within the same DB write transaction as the note.
    Handles create (empty -> new tags), update (old -> new tags), and delete
    (call with tags=[] to remove all rows for this note).
    """
    await _sync_index("note", note_id, tags, session)


async def sync_document_tag_index(
    document_id: str,
    tags: list[str],
    session: AsyncSession,
    *,
    record_manual_provenance: bool = False,
) -> None:
    """Sync DocumentTagIndexModel and CanonicalTagModel.usage_count for a document.

    Mirrors sync_tag_index for documents. Call with tags=[] on deletion to
    remove every row for this document and decrement counts.

    When `record_manual_provenance=True`, also INSERT OR IGNORE a
    DocumentTagProvenanceModel row with source='manual' for every tag in the
    new list. Used by the manual PATCH paths so the prune endpoint can
    distinguish user-set tags from auto-generated ones. The auto-tagger
    writes its own provenance rows explicitly with the right tagger_version
    and should NOT pass this flag (would cross-label its writes as manual).
    """
    tags = await _sync_index("document", document_id, tags, session)
    if record_manual_provenance:
        repo = TagRepo(session)
        for tag in tags:
            await repo.record_manual_provenance(document_id, tag)


async def sync_note_sources(
    note_id: str, source_document_ids: list[str], session: AsyncSession
) -> None:
    """Sync NoteSourceModel rows for a note

    Deletes rows not in new list; inserts new rows via INSERT OR IGNORE (idempotent).
    """
    await NoteRepo(session).replace_sources(
        note_id, source_document_ids, datetime.now(UTC).isoformat()
    )


async def upsert_note_graph(
    note_id: str, content: str, document_id: str | None, tags: list[str]
) -> None:
    """Fire-and-forget: refresh the entities the note is about."""
    try:
        await _note_graph_module.get_note_graph_service().upsert_note_node(
            note_id, content, document_id, tags
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
            row = await NoteRepo(session).content_of(note_id)
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


async def generate_and_store_description(note_id: str, content: str) -> None:
    """Background: summarise note content and persist it as the card description.

    Runs off the request path so saving stays instant. Skips the write if the
    note was deleted or its content changed since this task was scheduled, so a
    stale summary never clobbers a newer one. Non-fatal on any failure.
    """
    try:
        from app.services.note_description_generator import (  # noqa: PLC0415
            get_description_generator,
        )

        description = await get_description_generator().suggest_description(content)
        if description is None:
            return  # too short or LLM unavailable -> leave null, card shows snippet
        async with get_session_factory()() as session:
            note = await NoteRepo(session).find(note_id)
            if note is None or note.content != content:
                return
            note.description = description
            await session.commit()
        logger.debug("Note description stored note_id=%s", note_id)
    except Exception as exc:
        logger.warning("generate_and_store_description failed (non-fatal): %s", exc)


async def auto_tag_and_store_note(note_id: str, content: str) -> None:
    """Background: suggest tags for a note created with none, and persist them.

    Runs off the request path -- the tagger's LLM call queues behind whatever
    else holds the model (a background ingestion job can occupy it for
    minutes), and awaiting it inline made every note save, and the "Open full
    note" navigation gated on that save, hang for as long as the queue was
    busy. Skips the write if the note was deleted, tagged since (by the user
    or a race with this same task), or its content changed, so a stale
    suggestion never clobbers a newer state. Non-fatal on any failure.
    """
    try:
        raw_tags = await _note_tagger_module.get_note_tagger().suggest_tags(content)
        tags = [nt for t in raw_tags if (nt := normalize_tag_slug(t))]
        if not tags:
            return
        async with get_session_factory()() as session:
            note = await NoteRepo(session).find(note_id)
            if note is None or note.content != content or note.tags:
                return
            note.tags = tags
            await sync_tag_index(note_id, tags, session)
            await EngagementService(session).award_note_tag_bonus(note_id, len(tags))
            await session.commit()
        logger.debug("Note auto-tagged note_id=%s tags=%d", note_id, len(tags))
    except Exception as exc:
        logger.warning("auto_tag_and_store_note failed (non-fatal): %s", exc)


async def backfill_missing_descriptions(limit: int = 500, force: bool = False) -> int:
    """Summarise existing notes. By default only fills notes that have no
    description yet (e.g. created before the feature); ``force=True`` refreshes
    every eligible note. Sequential and best-effort so it stays a gentle
    background job; notes left null when the LLM is down are retried later.
    """
    async with get_session_factory()() as session:
        rows = await NoteRepo(session).needing_description(force=force, limit=limit)
    done = 0
    for note_id, content in rows:
        await generate_and_store_description(note_id, content)
        done += 1
    if done:
        logger.info("Backfilled descriptions for %d note(s)", done)
    return done
