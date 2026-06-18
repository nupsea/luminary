"""Concept correction endpoints -- the "review what Lumen found" backend.

Each correction mutates the concept AND records an Override keyed by slug, so the
user's decision survives re-parse (I-22; docs/concepts.md). Thin handlers over
ConceptService.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ConceptModel, FlashcardModel, NoteModel
from app.services.concept_service import get_concept_service
from app.services.graph import get_graph_service

_LEXICAL_SCAN_CAP = 500
_WARMTH_DECAY_DAYS = 18.0  # warmth 1 (fresh) -> 0 (cold) over this window

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/concepts", tags=["concepts"])


class ConceptOut(BaseModel):
    id: str
    slug: str
    label: str
    kind: str
    status: str
    mastery: float


class RenameRequest(BaseModel):
    label: str


class ReclassifyRequest(BaseModel):
    kind: str  # concept | keyword


class MergeRequest(BaseModel):
    source_id: str
    target_id: str


def _out(row: ConceptModel) -> ConceptOut:
    return ConceptOut(
        id=row.id, slug=row.slug, label=row.label, kind=row.kind,
        status=row.status, mastery=row.mastery,
    )


class UniverseStar(BaseModel):
    id: str
    label: str
    kind: str
    status: str
    mastery: float
    warmth: float  # 0 cold .. 1 fresh (mastery x recency drives the glow)


class UniverseEdge(BaseModel):
    source: str
    target: str


class UniverseResponse(BaseModel):
    stars: list[UniverseStar]
    edges: list[UniverseEdge]


def _warmth(last_reviewed: datetime | None, now: datetime) -> float:
    if last_reviewed is None:
        return 0.0
    if last_reviewed.tzinfo is None:
        last_reviewed = last_reviewed.replace(tzinfo=UTC)
    days = (now - last_reviewed).total_seconds() / 86400.0
    return max(0.0, min(1.0, 1.0 - days / _WARMTH_DECAY_DAYS))


@router.get("/universe", response_model=UniverseResponse)
async def get_universe(session: AsyncSession = Depends(get_db)) -> UniverseResponse:
    """The Knowledge Universe: concept stars (warmth = mastery x recency) + edges.

    Baseline sky is always meaningful; edges appear only when the concept linker has
    produced CONCEPT_RELATED_TO relations (degrades gracefully -- docs/universe.md).
    """
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(ConceptModel).where(ConceptModel.status != "candidate")
        )
    ).scalars().all()
    stars = [
        UniverseStar(
            id=c.id, label=c.label, kind=c.kind, status=c.status,
            mastery=c.mastery, warmth=_warmth(c.last_reviewed, now),
        )
        for c in rows
    ]
    star_ids = {c.id for c in rows}
    try:
        relations = get_graph_service().get_concept_relations()
    except Exception:
        logger.warning("universe: concept relations lookup failed", exc_info=True)
        relations = []
    edges = [
        UniverseEdge(source=r["source"], target=r["target"])
        for r in relations
        if r["source"] in star_ids and r["target"] in star_ids
    ]
    return UniverseResponse(stars=stars, edges=edges)


@router.get("/{concept_id}", response_model=ConceptOut)
async def get_concept(concept_id: str, session: AsyncSession = Depends(get_db)) -> ConceptOut:
    row = await session.get(ConceptModel, concept_id)
    if row is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return _out(row)


@router.post("/{concept_id}/rename", response_model=ConceptOut)
async def rename_concept(
    concept_id: str, req: RenameRequest, session: AsyncSession = Depends(get_db)
) -> ConceptOut:
    label = req.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="label is required")
    row = await get_concept_service().rename_concept(session, concept_id, label)
    if row is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await session.commit()
    return _out(row)


@router.post("/{concept_id}/reclassify", response_model=ConceptOut)
async def reclassify_concept(
    concept_id: str, req: ReclassifyRequest, session: AsyncSession = Depends(get_db)
) -> ConceptOut:
    try:
        row = await get_concept_service().reclassify_concept(session, concept_id, req.kind)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await session.commit()
    return _out(row)


@router.post("/{concept_id}/confirm", status_code=204)
async def confirm_concept(concept_id: str, session: AsyncSession = Depends(get_db)) -> None:
    if await session.get(ConceptModel, concept_id) is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await get_concept_service().confirm_concept(session, concept_id)
    await session.commit()


@router.post("/{concept_id}/reject", status_code=204)
async def reject_concept(concept_id: str, session: AsyncSession = Depends(get_db)) -> None:
    if await session.get(ConceptModel, concept_id) is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await get_concept_service().reject_concept(session, concept_id)
    await session.commit()


@router.post("/merge", response_model=ConceptOut)
async def merge_concepts(
    req: MergeRequest, session: AsyncSession = Depends(get_db)
) -> ConceptOut:
    row = await get_concept_service().merge_concepts(session, req.source_id, req.target_id)
    if row is None:
        raise HTTPException(status_code=404, detail="source or target concept not found")
    await session.commit()
    return _out(row)


@router.post("/apply-overrides")
async def apply_overrides(session: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Re-apply all stored overrides onto the current concepts (re-parse hook, I-22)."""
    applied = await get_concept_service().apply_overrides(session)
    await session.commit()
    return {"applied": applied}


@router.get("/for-note/{note_id}", response_model=list[ConceptOut])
async def concepts_for_note(
    note_id: str, session: AsyncSession = Depends(get_db)
) -> list[ConceptOut]:
    """Concepts a note touches (docs/03-notes-generation.md).

    Two signals, unioned: (1) engagement -- concepts the note's mapped cards point at;
    (2) lexical recall -- concepts whose label appears in the note's title/content. This
    is the always-on degraded path; the concept_linker labs feature enriches it later.
    """
    note = await session.get(NoteModel, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")

    mapped_ids = {
        cid
        for cid in (
            await session.execute(
                select(FlashcardModel.concept_id).where(
                    FlashcardModel.note_id == note_id,
                    FlashcardModel.concept_id.is_not(None),
                )
            )
        ).scalars().all()
        if cid
    }

    text = f"{note.title or ''}\n{note.content or ''}".lower()
    candidates = (
        await session.execute(select(ConceptModel).limit(_LEXICAL_SCAN_CAP))
    ).scalars().all()

    out: list[ConceptModel] = []
    seen: set[str] = set()
    for c in candidates:
        if c.id in mapped_ids or (c.label and c.label.lower() in text):
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
    # include mapped concepts that fell outside the lexical scan cap
    missing = mapped_ids - seen
    if missing:
        extra = (
            await session.execute(select(ConceptModel).where(ConceptModel.id.in_(missing)))
        ).scalars().all()
        out.extend(extra)

    out.sort(key=lambda c: c.mastery)  # weakest first
    return [_out(c) for c in out]


@router.get("")
async def list_concepts(
    status: str | None = None, session: AsyncSession = Depends(get_db)
) -> list[ConceptOut]:
    """List concepts, optionally filtered by status (e.g. ?status=proposed for review)."""
    stmt = select(ConceptModel)
    if status:
        stmt = stmt.where(ConceptModel.status == status)
    rows = (await session.execute(stmt.order_by(ConceptModel.mastery.asc()))).scalars().all()
    return [_out(r) for r in rows]
