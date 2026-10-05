"""Which flashcards a due-queue request covers: explicit ids, a collection tree, a tag."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos.collection_repo import CollectionRepo
from app.repos.document_repo import DocumentRepo
from app.repos.study_repo import DueScope
from app.repos.tag_repo import TagRepo
from app.services.documents_service import safe_tags


async def _documents_tagged(
    session: AsyncSession, tag: str, within: Sequence[str] | None
) -> list[str]:
    rows = await DocumentRepo(session).tags_by_id(within)
    return [doc_id for doc_id, tags in rows if tag in safe_tags(tags)]


async def due_scope(
    session: AsyncSession,
    *,
    document_ids: Sequence[str] | None = None,
    note_ids: Sequence[str] | None = None,
    collection_id: str | None = None,
    tag: str | None = None,
    section_id: str | None = None,
) -> DueScope:
    """Explicit ids override the collection; a tag narrows whichever applies."""
    pool: tuple[list[str], list[str]] | None = None
    if collection_id and not (document_ids or note_ids):
        doc_ids, member_note_ids = await CollectionRepo(session).member_ids_recursive(collection_id)
        if tag:
            doc_ids = await _documents_tagged(session, tag, doc_ids)
            tagged = set(await TagRepo(session).note_ids_with_tag(tag))
            member_note_ids = [n for n in member_note_ids if n in tagged]
        pool = (doc_ids, member_note_ids)
    elif tag:
        pool = (
            await _documents_tagged(session, tag, None),
            await TagRepo(session).note_ids_with_tag(tag),
        )
    return DueScope(
        document_ids=document_ids or (),
        note_ids=note_ids or (),
        section_id=section_id,
        pool=pool,
    )
