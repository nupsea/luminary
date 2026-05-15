"""Mastery endpoints

Routes:
  GET /mastery/concepts?document_ids=id1&document_ids=id2 -- sorted concept mastery list
  GET /mastery/heatmap?document_id={id}                   -- chapter x concept grid

Both return HTTP 200 with empty data structures when no data exists.
"""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.mastery_service import get_mastery_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mastery"])


class ConceptMasteryOut(BaseModel):
    concept: str
    mastery: float
    card_count: int
    due_soon: int
    no_flashcards: bool
    document_ids: list[str]


class MasteryConceptsOut(BaseModel):
    document_ids: list[str]
    concepts: list[ConceptMasteryOut]


class HeatmapCellOut(BaseModel):
    chapter: str
    concept: str
    mastery: float | None
    card_count: int


class MasteryHeatmapOut(BaseModel):
    document_id: str
    chapters: list[str]
    concepts: list[str]
    cells: list[HeatmapCellOut]


@router.get("/mastery/concepts", response_model=MasteryConceptsOut)
async def get_mastery_concepts(
    document_ids: list[str] = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db),
) -> MasteryConceptsOut:
    """Return concept mastery list sorted by mastery ascending (weakest first)."""
    svc = get_mastery_service()
    concepts = await svc.get_all_concept_masteries(document_ids, session)
    return MasteryConceptsOut(
        document_ids=document_ids,
        concepts=[
            ConceptMasteryOut(
                concept=c.concept,
                mastery=c.mastery,
                card_count=c.card_count,
                due_soon=c.due_soon,
                no_flashcards=c.no_flashcards,
                document_ids=c.document_ids,
            )
            for c in concepts
        ],
    )


@router.get("/mastery/heatmap", response_model=MasteryHeatmapOut)
async def get_mastery_heatmap(
    document_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> MasteryHeatmapOut:
    """Return chapter x concept mastery grid for a single document."""
    svc = get_mastery_service()
    result = await svc.get_heatmap(document_id, session)
    return MasteryHeatmapOut(
        document_id=result["document_id"],
        chapters=result["chapters"],
        concepts=result["concepts"],
        cells=[
            HeatmapCellOut(
                chapter=cell.chapter,
                concept=cell.concept,
                mastery=cell.mastery,
                card_count=cell.card_count,
            )
            for cell in result["cells"]
        ],
    )
