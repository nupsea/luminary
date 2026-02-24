"""Flashcard CRUD and generation endpoints.

Routes:
  POST /flashcards/generate            — LLM-generate cards for a document
  GET  /flashcards/{document_id}       — list cards ordered by created_at desc
  PUT  /flashcards/{card_id}           — update question/answer, sets is_user_edited
  DELETE /flashcards/{card_id}         — delete a card (204)
  GET  /flashcards/{document_id}/export/csv — CSV download
"""

import csv
import io
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DocumentModel, FlashcardModel
from app.services.flashcard import FlashcardService, get_flashcard_service

router = APIRouter(prefix="/flashcards", tags=["flashcards"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class FlashcardGenerateRequest(BaseModel):
    document_id: str
    scope: Literal["full", "section"] = "full"
    section_heading: str | None = None
    count: int = 10


class FlashcardUpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None


class FlashcardResponse(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    question: str
    answer: str
    source_excerpt: str
    is_user_edited: bool
    fsrs_state: str
    fsrs_stability: float
    fsrs_difficulty: float
    due_date: datetime | None
    reps: int
    lapses: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(card: FlashcardModel) -> FlashcardResponse:
    return FlashcardResponse(
        id=card.id,
        document_id=card.document_id,
        chunk_id=card.chunk_id,
        question=card.question,
        answer=card.answer,
        source_excerpt=card.source_excerpt,
        is_user_edited=card.is_user_edited,
        fsrs_state=card.fsrs_state,
        fsrs_stability=card.fsrs_stability,
        fsrs_difficulty=card.fsrs_difficulty,
        due_date=card.due_date,
        reps=card.reps,
        lapses=card.lapses,
        created_at=card.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=list[FlashcardResponse], status_code=201)
async def generate_flashcards(
    req: FlashcardGenerateRequest,
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> list[FlashcardResponse]:
    """Generate flashcards for a document using LLM."""
    cards = await service.generate(
        document_id=req.document_id,
        scope=req.scope,
        section_heading=req.section_heading,
        count=req.count,
        session=session,
    )
    return [_to_response(c) for c in cards]


@router.get("/{document_id}/export/csv")
async def export_flashcards_csv(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all flashcards for a document as a CSV download."""
    doc_result = await session.execute(
        select(DocumentModel).where(DocumentModel.id == document_id)
    )
    doc = doc_result.scalar_one_or_none()
    document_title = doc.title if doc else ""

    card_result = await session.execute(
        select(FlashcardModel)
        .where(FlashcardModel.document_id == document_id)
        .order_by(FlashcardModel.created_at.desc())
    )
    cards = card_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["question", "answer", "source_excerpt", "document_title"])
    for card in cards:
        writer.writerow([card.question, card.answer, card.source_excerpt, document_title])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flashcards.csv"},
    )


@router.get("/{document_id}", response_model=list[FlashcardResponse])
async def list_flashcards(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[FlashcardResponse]:
    """List all flashcards for a document ordered by created_at desc."""
    result = await session.execute(
        select(FlashcardModel)
        .where(FlashcardModel.document_id == document_id)
        .order_by(FlashcardModel.created_at.desc())
    )
    cards = result.scalars().all()
    return [_to_response(c) for c in cards]


@router.put("/{card_id}", response_model=FlashcardResponse)
async def update_flashcard(
    card_id: str,
    req: FlashcardUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> FlashcardResponse:
    """Update a flashcard's question and/or answer. Sets is_user_edited=True."""
    result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    if req.question is not None:
        card.question = req.question
    if req.answer is not None:
        card.answer = req.answer
    card.is_user_edited = True

    await session.commit()
    await session.refresh(card)
    return _to_response(card)


@router.delete("/{card_id}", status_code=204)
async def delete_flashcard(
    card_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a flashcard by ID."""
    result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    await session.execute(delete(FlashcardModel).where(FlashcardModel.id == card_id))
    await session.commit()
