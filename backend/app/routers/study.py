"""Study session endpoints.

Routes:
  GET  /study/due                    — flashcards due for review (due_date <= now)
  POST /study/sessions/start         — create a new study session
  POST /study/sessions/{id}/end      — close a session and return summary
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FlashcardModel, ReviewEventModel, StudySessionModel
from app.routers.flashcards import FlashcardResponse, _to_response

router = APIRouter(prefix="/study", tags=["study"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    document_id: str | None = None
    mode: str = "flashcard"


class SessionResponse(BaseModel):
    id: str
    document_id: str | None
    started_at: datetime
    ended_at: datetime | None
    cards_reviewed: int
    cards_correct: int
    mode: str

    model_config = {"from_attributes": True}


class SessionSummary(BaseModel):
    session_id: str
    cards_reviewed: int
    cards_correct: int
    ended_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/due", response_model=list[FlashcardResponse])
async def get_due_cards(
    document_id: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_db),
) -> list[FlashcardResponse]:
    """Return flashcards whose due_date is now or in the past."""
    now = datetime.utcnow()
    stmt = select(FlashcardModel).where(FlashcardModel.due_date <= now)
    if document_id:
        stmt = stmt.where(FlashcardModel.document_id == document_id)
    stmt = stmt.order_by(FlashcardModel.due_date.asc()).limit(limit)
    result = await session.execute(stmt)
    cards = result.scalars().all()
    return [_to_response(c) for c in cards]


@router.post("/sessions/start", response_model=SessionResponse, status_code=201)
async def start_session(
    req: StartSessionRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Create a new study session row and return its ID."""
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        started_at=datetime.utcnow(),
        cards_reviewed=0,
        cards_correct=0,
        mode=req.mode,
    )
    session.add(sess)
    await session.commit()
    await session.refresh(sess)
    return SessionResponse.model_validate(sess)


@router.post("/sessions/{session_id}/end", response_model=SessionSummary)
async def end_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> SessionSummary:
    """Close a study session, tally review events, and return the summary."""
    result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    sess = result.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events_result = await db.execute(
        select(ReviewEventModel).where(ReviewEventModel.session_id == session_id)
    )
    events = events_result.scalars().all()

    cards_reviewed = len(events)
    cards_correct = sum(1 for e in events if e.is_correct)

    sess.ended_at = datetime.utcnow()
    sess.cards_reviewed = cards_reviewed
    sess.cards_correct = cards_correct
    await db.commit()
    await db.refresh(sess)

    return SessionSummary(
        session_id=sess.id,
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        ended_at=sess.ended_at,
    )
