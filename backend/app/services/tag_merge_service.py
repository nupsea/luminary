"""Shared tag-merge orchestration.

Both `POST /tags/merge` and `POST /tags/normalization/suggestions/{id}/accept`
need the same five-step "merge tag A into tag B" cascade:

  1. Find every note tagged with `source_id` via NoteTagIndexModel.
  2. For each note: replace `source_id` -> `target_id` in note.tags
     (deduplicating, order-preserving), flag the JSON column dirty,
     re-sync the tag index, all in one transaction.
  3. Add a `TagAliasModel(alias=source_id, canonical_tag_id=target_id)`
     row so future lookups follow the merge.
  4. Delete the `CanonicalTagModel` row for `source_id`.
  5. Invalidate the tag-graph cache (read-side, lru cached).

On any failure the whole transaction rolls back. This service does NOT
own the session; the router passes one in so the surrounding endpoint
controls commit/error mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models import (
    CanonicalTagModel,
    DocumentModel,
    DocumentTagIndexModel,
    NoteModel,
    NoteTagIndexModel,
    TagAliasModel,
)
from app.services.notes_service import sync_document_tag_index, sync_tag_index
from app.services.tag_graph import invalidate_tag_graph_cache

logger = logging.getLogger(__name__)


@dataclass
class TagMergeResult:
    affected_notes: int
    affected_documents: int = 0


class TagMergeService:
    async def merge_tag(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        target_id: str,
        commit: bool = True,
    ) -> TagMergeResult:
        """Merge `source_id` into `target_id` across notes and documents.

        Caller has already validated both tags exist and that source != target.
        If `commit` is False, the caller is responsible for committing or
        rolling back. This is how `accept_normalization_suggestion` runs
        the merge inside its own transaction that also updates the
        suggestion's `status` field.
        """
        affected_notes = await self._update_notes(session, source_id, target_id)
        affected_documents = await self._update_documents(session, source_id, target_id)
        self._add_alias(session, source_id=source_id, target_id=target_id)
        await self._delete_source_tag(session, source_id)
        if commit:
            await session.commit()
            session.expire_all()
            invalidate_tag_graph_cache()
        return TagMergeResult(
            affected_notes=affected_notes,
            affected_documents=affected_documents,
        )

    async def _update_notes(
        self,
        session: AsyncSession,
        source_id: str,
        target_id: str,
    ) -> int:
        """Rewrite the tags column for every note that contains source_id, and
        re-sync the NoteTagIndexModel rows. Returns the count of notes touched.
        """
        result = await session.execute(
            select(NoteTagIndexModel.note_id)
            .where(NoteTagIndexModel.tag_full == source_id)
            .distinct()
        )
        note_ids = [row[0] for row in result.all()]
        if not note_ids:
            return 0

        # Ensure we are not using stale objects (the existing merge_tags
        # endpoint did this before the loop; preserved here for parity).
        session.expire_all()

        notes_result = await session.execute(
            select(NoteModel).where(NoteModel.id.in_(note_ids))
        )
        notes = list(notes_result.scalars().all())

        for note in notes:
            current_tags: list[str] = note.tags or []
            new_tags = _replace_tag(current_tags, source_id, target_id)
            note.tags = new_tags
            flag_modified(note, "tags")
            session.add(note)
            # Idempotent: even when current_tags == new_tags we re-sync so the
            # index reflects whatever the merge requested.
            await sync_tag_index(note.id, new_tags, session)

        # Force the rewrites to the DB before _update_documents runs. Without
        # this, autoflush ordering across the two updaters has been observed
        # to drop the in-memory note.tags changes in some test orderings.
        await session.flush()
        return len(notes)

    async def _update_documents(
        self,
        session: AsyncSession,
        source_id: str,
        target_id: str,
    ) -> int:
        """Mirror of _update_notes for DocumentModel + DocumentTagIndexModel."""
        result = await session.execute(
            select(DocumentTagIndexModel.document_id)
            .where(DocumentTagIndexModel.tag_full == source_id)
            .distinct()
        )
        doc_ids = [row[0] for row in result.all()]
        if not doc_ids:
            return 0

        docs_result = await session.execute(
            select(DocumentModel).where(DocumentModel.id.in_(doc_ids))
        )
        docs = list(docs_result.scalars().all())

        for doc in docs:
            current_tags: list[str] = doc.tags or []
            new_tags = _replace_tag(current_tags, source_id, target_id)
            doc.tags = new_tags
            flag_modified(doc, "tags")
            session.add(doc)
            await sync_document_tag_index(doc.id, new_tags, session)

        await session.flush()
        return len(docs)

    def _add_alias(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        target_id: str,
    ) -> None:
        session.add(TagAliasModel(alias=source_id, canonical_tag_id=target_id))

    async def _delete_source_tag(
        self, session: AsyncSession, source_id: str
    ) -> None:
        await session.execute(
            delete(CanonicalTagModel).where(CanonicalTagModel.id == source_id)
        )


def _replace_tag(current: list[str], source_id: str, target_id: str) -> list[str]:
    """Order-preserving, dedup-aware replacement of source_id with target_id."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in current:
        replacement = target_id if tag == source_id else tag
        if replacement not in seen:
            seen.add(replacement)
            out.append(replacement)
    return out


def get_tag_merge_service() -> TagMergeService:
    return TagMergeService()
