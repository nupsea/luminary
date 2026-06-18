"""study_assembler: build a Study Event's item set from a Launcher scope.

The keystone of the two-lane model (docs/study-launcher.md). Resolves a scope to
its concepts, interleaves due FSRS cards (and, later, freshly generated questions),
fits the time budget, and reports an honest preview (due vs generated, mapped vs
unmapped, topic mix, thin-scope warning).

Pure: it reads and assembles but writes nothing. The router owns the StudyEvent row
and the transaction. Honors I-1 (single session, no shared-session gather), I-2
(LanceDB via to_thread -- only reached through scope_resolver), I-3 (Kuzu guards in
the graph repo).

Generation (Lane B) is a seam here: `want_generated` is accepted and surfaced in the
preview, but minting new questions from material is wired by a later Phase 1 increment.
Until then the assembler ships the due-card path so one-tap Start always yields a
valid event.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CollectionMemberModel, ConceptModel, FlashcardModel
from app.services.scope_resolver import resolve_scope

logger = logging.getLogger(__name__)

# rough cards-per-minute so a 5/15/25-min budget maps to a sane item count
_ITEMS_PER_MIN = 1.2
_MIN_ITEMS = 3
_MAX_ITEMS = 40
_THIN_SCOPE_ITEMS = 3


def items_for_budget(length_min: int) -> int:
    return max(_MIN_ITEMS, min(_MAX_ITEMS, round(length_min * _ITEMS_PER_MIN)))


@dataclass
class AssemblyPreview:
    due_count: int = 0
    generated_count: int = 0
    mapped_count: int = 0
    unmapped_count: int = 0
    topic_mix: list[str] = field(default_factory=list)
    thin_scope_warning: str | None = None


@dataclass
class AssemblyResult:
    concept_ids: list[str]
    card_ids: list[str]
    cards: list[FlashcardModel]
    preview: AssemblyPreview


async def _material_ids(
    session: AsyncSession, scope_type: str, scope_ref: str | None
) -> tuple[list[str], list[str]]:
    """document_ids, note_ids for a scope -- so due unmapped cards are still caught."""
    if scope_ref is None:
        return [], []
    if scope_type == "doc":
        return [scope_ref], []
    if scope_type == "note":
        return [], [scope_ref]
    if scope_type == "collection":
        doc_ids = (
            await session.execute(
                select(CollectionMemberModel.member_id).where(
                    CollectionMemberModel.collection_id == scope_ref,
                    CollectionMemberModel.member_type == "document",
                )
            )
        ).scalars().all()
        note_ids = (
            await session.execute(
                select(CollectionMemberModel.member_id).where(
                    CollectionMemberModel.collection_id == scope_ref,
                    CollectionMemberModel.member_type == "note",
                )
            )
        ).scalars().all()
        return list(doc_ids), list(note_ids)
    return [], []


async def assemble(
    session: AsyncSession,
    scope_type: str,
    scope_ref: str | None = None,
    *,
    length_min: int = 5,
    want_generated: bool = True,
) -> AssemblyResult:
    """Resolve scope -> due cards (mapped by concept + unmapped by material), budget-fit."""
    concept_ids = await resolve_scope(session, scope_type, scope_ref)
    doc_ids, note_ids = await _material_ids(session, scope_type, scope_ref)
    budget = items_for_budget(length_min)

    now = datetime.now(UTC)
    conds = []
    if concept_ids:
        conds.append(FlashcardModel.concept_id.in_(concept_ids))
    if doc_ids:
        conds.append(FlashcardModel.document_id.in_(doc_ids))
    if note_ids:
        conds.append(FlashcardModel.note_id.in_(note_ids))

    cards: list[FlashcardModel] = []
    if conds:
        stmt = (
            select(FlashcardModel)
            .where(FlashcardModel.due_date <= now, or_(*conds))
            .order_by(FlashcardModel.due_date.asc())
            .limit(budget)
        )
        cards = list((await session.execute(stmt)).scalars().all())

    mapped = sum(1 for c in cards if c.concept_id)
    preview = AssemblyPreview(
        due_count=len(cards),
        generated_count=0,  # generation seam -- wired in a later Phase 1 increment
        mapped_count=mapped,
        unmapped_count=len(cards) - mapped,
        topic_mix=await _topic_mix(session, concept_ids),
    )
    if want_generated:
        # honest: generation is requested but not yet producing items
        logger.debug("assemble: generation requested but not yet wired (generated=0)")
    if len(cards) <= _THIN_SCOPE_ITEMS and not concept_ids:
        preview.thin_scope_warning = (
            "This scope has little tracked material -- expect a short event."
        )

    return AssemblyResult(
        concept_ids=concept_ids,
        card_ids=[c.id for c in cards],
        cards=cards,
        preview=preview,
    )


async def _topic_mix(session: AsyncSession, concept_ids: list[str], limit: int = 4) -> list[str]:
    if not concept_ids:
        return []
    rows = (
        await session.execute(
            select(ConceptModel.label).where(ConceptModel.id.in_(concept_ids[:limit]))
        )
    ).scalars().all()
    return list(rows)
