"""Study session endpoints.

Routes:
  GET  /study/due                    — flashcards due for review (due_date <= now)
  POST /study/sessions/start         — create a new study session
  POST /study/sessions/{id}/end      — close a session and return summary
  GET  /study/gaps/{document_id}     — weak flashcard areas grouped by section
  POST /study/teachback              — LLM evaluation of user's teach-back explanation
"""

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ChunkModel,
    FlashcardModel,
    MisconceptionModel,
    ReviewEventModel,
    SectionModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.routers.flashcards import FlashcardResponse, _to_response
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/study", tags=["study"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAP_STABILITY_THRESHOLD = 2.0
_GAP_MIN_REPS = 1

_TEACHBACK_SYSTEM = (
    "You are a Socratic tutor evaluating a student's explanation. "
    "Output only valid JSON, no markdown fences, no preamble."
)

_TEACHBACK_USER_TMPL = (
    "The correct answer to the question is: {answer}\n"
    "The student explained: {explanation}\n\n"
    "Evaluate whether the student's explanation is accurate and complete. "
    "Score 0-100 (100 = perfectly correct and complete). "
    "Identify specific correct points, missing points, and misconceptions.\n"
    'Output JSON: {{"score": int, "correct_points": [str], '
    '"missing_points": [str], "misconceptions": [str]}}'
)

_CORRECTION_SYSTEM = (
    "You are a flashcard generator creating a targeted correction card. "
    "Output only valid JSON, no markdown fences."
)

_CORRECTION_USER_TMPL = (
    "The student has this misconception: {misconception}\n"
    'The correct answer to "{question}" is: {answer}\n\n'
    "Write a focused correction flashcard that addresses this specific misconception. "
    'Output JSON: {{"question": str, "answer": str, "source_excerpt": str}}'
)


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


class GapResult(BaseModel):
    section_heading: str | None
    weak_card_count: int
    avg_stability: float
    sample_questions: list[str]


class TeachbackRequest(BaseModel):
    flashcard_id: str
    user_explanation: str


class TeachbackResponse(BaseModel):
    score: int
    correct_points: list[str]
    missing_points: list[str]
    misconceptions: list[str]
    correction_flashcard_id: str | None = None


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


@router.get("/gaps/{document_id}", response_model=list[GapResult])
async def get_gaps(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[GapResult]:
    """Return sections with weak (seen but fragile) flashcards, ordered by avg stability."""
    # Load weak cards for this document
    weak_stmt = (
        select(FlashcardModel)
        .where(FlashcardModel.document_id == document_id)
        .where(FlashcardModel.fsrs_stability < _GAP_STABILITY_THRESHOLD)
        .where(FlashcardModel.reps > _GAP_MIN_REPS)
    )
    weak_result = await session.execute(weak_stmt)
    weak_cards = weak_result.scalars().all()

    if not weak_cards:
        return []

    # For each weak card, resolve its section heading via chunk → section join
    # Build a mapping: card_id → section_heading
    chunk_ids = [c.chunk_id for c in weak_cards]
    chunk_stmt = select(ChunkModel, SectionModel.heading).outerjoin(
        SectionModel, ChunkModel.section_id == SectionModel.id
    ).where(ChunkModel.id.in_(chunk_ids))
    chunk_rows = await session.execute(chunk_stmt)

    chunk_to_section: dict[str, str | None] = {}
    for chunk, heading in chunk_rows:
        chunk_to_section[chunk.id] = heading

    # Group by section heading
    groups: dict[str | None, list[FlashcardModel]] = {}
    for card in weak_cards:
        heading = chunk_to_section.get(card.chunk_id)
        groups.setdefault(heading, []).append(card)

    results: list[GapResult] = []
    for heading, group_cards in groups.items():
        avg_stab = sum(c.fsrs_stability for c in group_cards) / len(group_cards)
        sample = [c.question for c in group_cards[:3]]
        results.append(
            GapResult(
                section_heading=heading,
                weak_card_count=len(group_cards),
                avg_stability=round(avg_stab, 4),
                sample_questions=sample,
            )
        )

    # Sort by avg_stability ascending (most fragile first)
    results.sort(key=lambda r: r.avg_stability)
    return results


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


@router.post("/teachback", response_model=TeachbackResponse)
async def teachback(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResponse:
    """Evaluate a student's teach-back explanation with LLM. Tracks misconceptions."""
    # Load flashcard
    card_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == req.flashcard_id)
    )
    card = card_result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # Call LLM to evaluate explanation
    llm = get_llm_service()
    prompt = _TEACHBACK_USER_TMPL.format(
        answer=card.answer,
        explanation=req.user_explanation,
    )
    raw = await llm.generate(prompt=prompt, system=_TEACHBACK_SYSTEM)

    # Parse LLM JSON response
    parsed = _parse_teachback_response(raw)
    score = parsed.get("score", 0)
    correct_points: list[str] = parsed.get("correct_points", [])
    missing_points: list[str] = parsed.get("missing_points", [])
    misconceptions: list[str] = parsed.get("misconceptions", [])

    # Persist teachback result
    tb_result = TeachbackResultModel(
        id=str(uuid.uuid4()),
        flashcard_id=card.id,
        user_explanation=req.user_explanation,
        score=score,
        correct_points=correct_points,
        missing_points=missing_points,
        misconceptions=misconceptions,
    )
    session.add(tb_result)

    correction_card_id: str | None = None

    # If score < 60 and there are misconceptions, create MisconceptionModel rows
    # and a correction flashcard
    if score < 60 and misconceptions:
        for m_text in misconceptions:
            misconception = MisconceptionModel(
                id=str(uuid.uuid4()),
                document_id=card.document_id,
                flashcard_id=card.id,
                user_answer=req.user_explanation,
                error_type="misconception",
                correction_note=m_text,
            )
            session.add(misconception)

        # Generate a correction flashcard targeting the first misconception
        correction_card_id = await _generate_correction_flashcard(
            card=card,
            misconception=misconceptions[0],
            session=session,
        )

    await session.commit()
    logger.info(
        "Teachback evaluated",
        extra={"flashcard_id": card.id, "score": score, "misconceptions": len(misconceptions)},
    )

    return TeachbackResponse(
        score=score,
        correct_points=correct_points,
        missing_points=missing_points,
        misconceptions=misconceptions,
        correction_flashcard_id=correction_card_id,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_teachback_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON from LLM teachback response."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse teachback JSON", extra={"raw": raw[:200]})
        return {"score": 0, "correct_points": [], "missing_points": [], "misconceptions": []}


async def _generate_correction_flashcard(
    card: FlashcardModel,
    misconception: str,
    session: AsyncSession,
) -> str | None:
    """Generate and store a correction flashcard targeting a specific misconception."""
    llm = get_llm_service()
    prompt = _CORRECTION_USER_TMPL.format(
        misconception=misconception,
        question=card.question,
        answer=card.answer,
    )
    raw = await llm.generate(prompt=prompt, system=_CORRECTION_SYSTEM)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse correction flashcard JSON")
        return None

    if not isinstance(data, dict):
        return None

    new_id = str(uuid.uuid4())
    correction = FlashcardModel(
        id=new_id,
        document_id=card.document_id,
        chunk_id=card.chunk_id,
        question=data.get("question", f"Correction: {card.question}"),
        answer=data.get("answer", card.answer),
        source_excerpt=data.get("source_excerpt", ""),
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=datetime.utcnow(),
        reps=0,
        lapses=0,
    )
    session.add(correction)
    return new_id


