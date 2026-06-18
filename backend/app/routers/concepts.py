"""Concept correction endpoints -- the "review what Lumen found" backend.

Each correction mutates the concept AND records an Override keyed by slug, so the
user's decision survives re-parse (I-22; docs/concepts.md). Thin handlers over
ConceptService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ConceptModel
from app.services.concept_service import get_concept_service

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
