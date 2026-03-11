"""Flashcard CRUD and generation endpoints.

Routes:
  POST /flashcards/generate            — LLM-generate cards for a document
  POST /flashcards/from-gaps           — one LLM flashcard per gap string (S97)
  GET  /flashcards/{document_id}/export/csv — CSV download
  GET  /flashcards/{document_id}       — list cards ordered by created_at desc
  PUT  /flashcards/{card_id}           — update question/answer, sets is_user_edited
  DELETE /flashcards/{card_id}         — delete a card (204)
  POST /flashcards/{card_id}/review    — FSRS review with rating
"""

import csv
import io
import logging
import uuid
from datetime import datetime
from typing import Literal

import litellm
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DocumentModel, FlashcardModel, ReviewEventModel
from app.services.flashcard import FlashcardService, get_flashcard_service
from app.services.fsrs_service import FSRSService, get_fsrs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flashcards", tags=["flashcards"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class FlashcardGenerateRequest(BaseModel):
    document_id: str
    scope: Literal["full", "section"] = "full"
    section_heading: str | None = None
    count: int = 10


class FromGapsRequest(BaseModel):
    gaps: list[str] = Field(min_length=1)
    document_id: str = ""


class FromGapsResponse(BaseModel):
    created: int


class FlashcardUpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]
    session_id: str | None = None


class FlashcardResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    source: str = "document"
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
        source=card.source if card.source else "document",
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
    try:
        cards = await service.generate(
            document_id=req.document_id,
            scope=req.scope,
            section_heading=req.section_heading,
            count=req.count,
            session=session,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve",
        ) from exc
    logger.info(
        "Generated flashcards",
        extra={"document_id": req.document_id, "count": len(cards)},
    )
    return [_to_response(c) for c in cards]


@router.post("/from-gaps", response_model=FromGapsResponse, status_code=200)
async def generate_from_gaps(
    req: FromGapsRequest,
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> FromGapsResponse:
    """Generate one LLM-authored flashcard per knowledge gap (S97).

    Raises 422 when gaps is empty. Raises 503 when Ollama is unreachable.
    """
    try:
        created, _ = await service.generate_from_gaps(
            gaps=req.gaps,
            document_id=req.document_id,
            session=session,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unreachable. Start it with: ollama serve",
        ) from exc
    logger.info("generate_from_gaps: created %d cards", created)
    return FromGapsResponse(created=created)


def _cards_to_csv(cards: list[FlashcardModel], document_title: str) -> str:
    """Render flashcards as a CSV string.

    Pure function — no I/O. All inputs are explicit parameters.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["question", "answer", "source_excerpt", "document_title"])
    for card in cards:
        writer.writerow([card.question, card.answer, card.source_excerpt, document_title])
    return output.getvalue()


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
    cards = list(card_result.scalars().all())

    return StreamingResponse(
        iter([_cards_to_csv(cards, document_title)]),
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
    logger.info("Updated flashcard", extra={"card_id": card_id})
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
    logger.info("Deleted flashcard", extra={"card_id": card_id})


@router.post("/{card_id}/review", response_model=FlashcardResponse)
async def review_flashcard(
    card_id: str,
    req: ReviewRequest,
    session: AsyncSession = Depends(get_db),
    service: FSRSService = Depends(get_fsrs_service),
) -> FlashcardResponse:
    """Submit an FSRS review rating for a flashcard. Optionally link to a study session."""
    try:
        card = await service.schedule(card_id, req.rating, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if req.session_id:
        event = ReviewEventModel(
            id=str(uuid.uuid4()),
            session_id=req.session_id,
            flashcard_id=card_id,
            rating=req.rating,
            is_correct=req.rating != "again",
        )
        session.add(event)
        await session.commit()

    logger.info("Reviewed flashcard", extra={"card_id": card_id, "rating": req.rating})
    return _to_response(card)
