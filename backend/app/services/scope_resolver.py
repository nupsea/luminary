"""scope_resolver: turn a Study Launcher scope into a set of concept ids.

One resolver per scope kind (see docs/study-launcher.md). Phase 0 implements the
document-grounded scopes that depend only on Concept data (daily, concept,
collection, doc). The generation-driven scopes (note, tag, selection, chat) resolve
to their already-linked concepts here; minting unmapped cards / candidate concepts
from free material is wired by the Study Launcher work in later phases.

Returns concept ids only -- the assembler (Phase 1) interleaves due cards and
generated questions on top. Honors I-3 (Kuzu has_next guards live in the graph repo).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CollectionMemberModel, ConceptModel, FlashcardModel
from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)

_DAILY_LIMIT = 20


async def _weakest_first(session: AsyncSession, concept_ids: list[str]) -> list[str]:
    """Order concept ids coldest/weakest first (the same selection everywhere)."""
    if not concept_ids:
        return []
    rows = (
        await session.execute(
            select(ConceptModel.id, ConceptModel.mastery, ConceptModel.last_reviewed).where(
                ConceptModel.id.in_(concept_ids)
            )
        )
    ).all()
    # never-reviewed (last_reviewed is None) sorts first, then lowest mastery
    order = sorted(rows, key=lambda r: (r[2] is not None, r[1]))
    return [r[0] for r in order]


async def resolve_daily(session: AsyncSession, limit: int = _DAILY_LIMIT) -> list[str]:
    """Lumen's cross-collection pick: weakest/coldest tracked concepts."""
    rows = (
        await session.execute(
            select(ConceptModel.id)
            .where(ConceptModel.status != "candidate")
            .order_by(ConceptModel.last_reviewed.is_(None).desc(), ConceptModel.mastery.asc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def _descendant_concept_ids(session: AsyncSession, node_id: str) -> list[str]:
    """All studyable (level-2) concept ids under a galaxy/constellation node."""
    children = (
        await session.execute(
            select(ConceptModel.id, ConceptModel.level).where(
                ConceptModel.parent_id == node_id
            )
        )
    ).all()
    leaves: list[str] = []
    for cid, level in children:
        if level >= 2:
            leaves.append(cid)
        else:
            leaves.extend(await _descendant_concept_ids(session, cid))
    return leaves


async def resolve_concept(session: AsyncSession, concept_id: str) -> list[str]:
    """Resolve a star to studyable concepts.

    A leaf concept (level 2) -> itself + its weakest related neighbours. A container
    (galaxy/constellation, level 0/1) -> all its descendant concepts, weakest first, so
    "Study this" on a domain assembles from everything inside it.
    """
    node = await session.get(ConceptModel, concept_id)
    if node is None:
        return []
    if node.level < 2:
        leaves = await _descendant_concept_ids(session, concept_id)
        if leaves:  # a real container; flat/legacy concepts (no children) fall through
            return await _weakest_first(session, leaves)
    neighbors = get_graph_service().get_concept_neighbors(concept_id, limit=8)
    ranked = await _weakest_first(session, [n for n in neighbors if n != concept_id])
    return [concept_id, *ranked[:2]]


async def resolve_doc(session: AsyncSession, document_id: str) -> list[str]:
    """Concepts extracted from a single document, weakest first."""
    ids = get_graph_service().get_concept_ids_for_documents([document_id])
    return await _weakest_first(session, ids)


async def _collection_document_ids(session: AsyncSession, collection_id: str) -> list[str]:
    rows = (
        await session.execute(
            select(CollectionMemberModel.member_id).where(
                CollectionMemberModel.collection_id == collection_id,
                CollectionMemberModel.member_type == "document",
            )
        )
    ).scalars().all()
    return list(rows)


async def resolve_collection(session: AsyncSession, collection_id: str) -> list[str]:
    """Concepts lit by the documents in a collection, weakest first."""
    doc_ids = await _collection_document_ids(session, collection_id)
    if not doc_ids:
        return []
    ids = get_graph_service().get_concept_ids_for_documents(doc_ids)
    return await _weakest_first(session, ids)


async def resolve_note(session: AsyncSession, note_id: str) -> list[str]:
    """Concepts a note's already-mapped cards point at (generation wired later)."""
    rows = (
        await session.execute(
            select(FlashcardModel.concept_id).where(
                FlashcardModel.note_id == note_id,
                FlashcardModel.concept_id.is_not(None),
            )
        )
    ).scalars().all()
    return await _weakest_first(session, list({r for r in rows if r}))


async def resolve_scope(
    session: AsyncSession, scope_type: str, scope_ref: str | None = None
) -> list[str]:
    """Dispatch a scope to its concept set. Unknown / not-yet-wired scopes return []."""
    if scope_type == "daily":
        return await resolve_daily(session)
    if scope_ref is None:
        return []
    if scope_type == "concept":
        return await resolve_concept(session, scope_ref)
    if scope_type == "doc":
        return await resolve_doc(session, scope_ref)
    if scope_type == "collection":
        return await resolve_collection(session, scope_ref)
    if scope_type == "note":
        return await resolve_note(session, scope_ref)
    # tag / selection / chat / planWeek: resolved by later-phase generation work.
    logger.debug("resolve_scope: scope_type %r not yet wired (returning [])", scope_type)
    return []
