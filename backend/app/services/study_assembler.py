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
_MAX_GENERATED = 10  # cap LLM-generated cards per event


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
    do_generate: bool = False,
) -> AssemblyResult:
    """Resolve scope -> due cards + (on commit) freshly generated questions, budget-fit.

    Lane B: `want_generated` surfaces an estimate in the preview; `do_generate` (set only on
    commit, when the model is up) actually runs the generator for doc/note scopes and persists
    the new cards. Honors constitution 9 -- generation failure degrades to the due-card set.
    """
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

    # Lane B generation. need = the gap to the budget. doc/note generate from their source;
    # a concept (or container that resolved to concepts) generates from concept evidence and
    # maps the new cards to the concept, so a freshly-regenerated sky is immediately studyable.
    need = max(0, budget - len(cards)) if want_generated else 0
    gen_from_scope = scope_type in ("doc", "note") and scope_ref is not None
    gen_from_concept = scope_type == "concept" and bool(concept_ids)
    generatable = gen_from_scope or gen_from_concept
    generated: list[FlashcardModel] = []
    generated_estimate = min(need, _MAX_GENERATED) if (need and generatable) else 0
    if do_generate and generated_estimate > 0:
        if gen_from_scope:
            generated = await _generate_for_scope(
                session, scope_type, scope_ref, generated_estimate
            )
        else:
            generated = await _generate_for_concepts(session, concept_ids, generated_estimate)
        cards.extend(generated)

    mapped = sum(1 for c in cards if c.concept_id)
    preview = AssemblyPreview(
        due_count=len(cards) - len(generated),
        generated_count=len(generated) if do_generate else generated_estimate,
        mapped_count=mapped,
        unmapped_count=len(cards) - mapped,
        topic_mix=await _topic_mix(session, concept_ids),
    )
    if len(cards) <= _THIN_SCOPE_ITEMS and not concept_ids and not generatable:
        preview.thin_scope_warning = (
            "This scope has little tracked material -- expect a short event."
        )

    return AssemblyResult(
        concept_ids=concept_ids,
        card_ids=[c.id for c in cards],
        cards=cards,
        preview=preview,
    )


async def _generate_for_scope(
    session: AsyncSession, scope_type: str, scope_ref: str, count: int
) -> list[FlashcardModel]:
    """Generate up to `count` new cards for a doc/note scope, tagged unmapped + scoped.

    Reuses the shipped FlashcardService generators. Degrades to [] on any failure
    (e.g. Ollama offline) so the event still starts from due cards (constitution 9).
    """
    from app.services.flashcard import FlashcardService  # noqa: PLC0415

    svc = FlashcardService()
    try:
        if scope_type == "doc":
            new = await svc.generate(scope_ref, "full", None, count, session)
        else:  # note
            new = await svc.generate_from_notes(None, [scope_ref], count, session)
    except Exception:
        logger.warning(
            "assemble: generation failed for %s:%s", scope_type, scope_ref, exc_info=True
        )
        return []

    # questions that map to no tracked concept are unmapped cards (docs/two-lane-model.md)
    for c in new:
        if c.concept_id is None:
            c.mapping_status = "unmapped"
        c.source_scope = f"{scope_type}:{scope_ref}"
    return new


async def _generate_for_concepts(
    session: AsyncSession, concept_ids: list[str], count: int
) -> list[FlashcardModel]:
    """Generate cards for concept scope, grounded in each concept's source document and
    MAPPED to the concept (so the concept builds a card set). Spreads `count` across the
    weakest concepts; degrades to [] on failure so the event still starts."""
    from app.services.flashcard import FlashcardService  # noqa: PLC0415

    svc = FlashcardService()
    out: list[FlashcardModel] = []
    targets = concept_ids[: max(1, min(len(concept_ids), 3))]
    per = max(1, count // len(targets))
    for cid in targets:
        if len(out) >= count:
            break
        concept = await session.get(ConceptModel, cid)
        if concept is None:
            continue
        ev = (concept.evidence_json or [{}])[0]
        doc_ids = ev.get("document_ids") or []
        if not doc_ids:
            continue
        members = ", ".join(ev.get("members", [])[:8])
        extra = f" ({members})." if members else "."
        ctx = f"Focus only on the concept '{concept.label}'" + extra
        try:
            new = await svc.generate(doc_ids[0], "full", None, per, session, context=ctx)
        except Exception:
            logger.warning("assemble: concept generation failed for %s", cid, exc_info=True)
            continue
        for c in new:
            c.concept_id = cid
            c.mapping_status = "mapped"
            c.source_scope = f"concept:{cid}"
        out.extend(new)
    return out[:count]


async def _topic_mix(session: AsyncSession, concept_ids: list[str], limit: int = 4) -> list[str]:
    if not concept_ids:
        return []
    rows = (
        await session.execute(
            select(ConceptModel.label).where(ConceptModel.id.in_(concept_ids[:limit]))
        )
    ).scalars().all()
    return list(rows)
