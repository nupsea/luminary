"""scope_resolver: turn a Study Launcher scope into a set of concept ids.

One resolver per scope kind (see docs/study-launcher.md). Phase 0 implements the
document-grounded scopes that depend only on Concept data (daily, concept,
collection, doc). The generation-driven scopes (note, tag, selection, chat) resolve
to their already-linked concepts here; minting unmapped cards / candidate concepts
from free material is wired by the Study Launcher work in later phases.

Returns concept ids only -- the assembler (Phase 1) interleaves due cards and
generated questions on top.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConceptModel
from app.repos.collection_repo import CollectionRepo
from app.repos.concept_repo import ConceptRepo
from app.repos.graph_concept_repo import GraphConceptRepo

logger = logging.getLogger(__name__)

_DAILY_LIMIT = 20


async def _weakest_first(session: AsyncSession, concept_ids: list[str]) -> list[str]:
    """Order concept ids coldest/weakest first (the same selection everywhere)."""
    if not concept_ids:
        return []
    concepts = await ConceptRepo(session).by_ids(concept_ids)
    # never-reviewed (last_reviewed is None) sorts first, then lowest mastery
    order = sorted(concepts, key=lambda c: (c.last_reviewed is not None, c.mastery))
    return [c.id for c in order]


async def resolve_daily(session: AsyncSession, limit: int = _DAILY_LIMIT) -> list[str]:
    """Lumen's cross-collection pick: weakest/coldest tracked concepts."""
    return await ConceptRepo(session).weakest_tracked(limit)


async def resolve_concept(session: AsyncSession, concept_id: str) -> list[str]:
    """Resolve a concept to studyable concepts: itself + its weakest related neighbours."""
    node = await session.get(ConceptModel, concept_id)
    if node is None:
        return []
    neighbors = await GraphConceptRepo(session).neighbors(concept_id, limit=8)
    ranked = await _weakest_first(session, [n for n in neighbors if n != concept_id])
    return [concept_id, *ranked[:2]]


async def resolve_doc(session: AsyncSession, document_id: str) -> list[str]:
    """Concepts extracted from a single document, weakest first."""
    ids = await GraphConceptRepo(session).concept_ids_for_documents([document_id])
    return await _weakest_first(session, ids)


async def resolve_collection(session: AsyncSession, collection_id: str) -> list[str]:
    """Concepts lit by the documents in a collection, weakest first."""
    doc_ids = await CollectionRepo(session).document_ids(collection_id)
    if not doc_ids:
        return []
    ids = await GraphConceptRepo(session).concept_ids_for_documents(doc_ids)
    return await _weakest_first(session, ids)


async def resolve_note(session: AsyncSession, note_id: str) -> list[str]:
    """Concepts a note's already-mapped cards point at (generation wired later)."""
    return await _weakest_first(
        session, list(await ConceptRepo(session).ids_on_note_cards(note_id))
    )


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
    # tag / selection / chat: resolved by later-phase generation work.
    logger.debug("resolve_scope: scope_type %r not yet wired (returning [])", scope_type)
    return []
