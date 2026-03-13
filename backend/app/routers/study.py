"""Study session endpoints.

Routes:
  GET  /study/due                    — flashcards due for review (due_date <= now)
  POST /study/sessions/start         — create a new study session
  POST /study/sessions/{id}/end      — close a session and return summary
  GET  /study/gaps/{document_id}     — weak flashcard areas grouped by section
  POST /study/teachback              — LLM evaluation of user's teach-back explanation
  GET  /study/stats/{document_id}    — progress stats: mastery, retention, streak
  GET  /study/history                — daily study activity for the last N days
  GET  /study/struggling             — cards with >= N 'again' ratings in last M days
"""

import json
import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    MisconceptionModel,
    ReviewEventModel,
    SectionModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.routers.flashcards import FlashcardResponse, _to_response
from app.services.fsrs_service import get_fsrs_service
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
    "Output a JSON object with no preamble or markdown."
)

_TEACHBACK_USER_TMPL = (
    "The correct answer to the question is: {answer}\n"
    "The student explained: {explanation}\n\n"
    "Evaluate the student's explanation for accuracy and completeness. "
    "Score 0 to 100. "
    "Identify correct points, missing points, and misconceptions.\n"
    'Output JSON: {{"score": int, "correct_points": [str], '
    '"missing_points": [str], "misconceptions": [str]}}'
)

_CORRECTION_SYSTEM = (
    "You are a flashcard generator creating a targeted correction card. "
    "Output a JSON object with no markdown."
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
    accuracy_pct: float
    ended_at: datetime


class SessionListItem(BaseModel):
    id: str
    started_at: datetime
    ended_at: datetime | None
    duration_minutes: float | None
    cards_reviewed: int
    cards_correct: int
    accuracy_pct: float | None
    document_id: str | None
    document_title: str | None
    mode: str

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    items: list[SessionListItem]
    total: int
    page: int
    page_size: int


class SessionCardDetail(BaseModel):
    flashcard_id: str
    question: str
    rating: str
    is_correct: bool
    reviewed_at: datetime


class GapResult(BaseModel):
    section_heading: str | None
    weak_card_count: int
    avg_stability: float
    sample_questions: list[str]


def _compute_gaps(
    weak_cards: list[FlashcardModel],
    chunk_to_section: dict[str, str | None],
) -> list[GapResult]:
    """Group weak cards by section, compute avg stability, return sorted results.

    Pure function — no I/O. All inputs are explicit parameters.
    """
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

    results.sort(key=lambda r: r.avg_stability)
    return results


class TeachbackRequest(BaseModel):
    flashcard_id: str
    user_explanation: str


class TeachbackResponse(BaseModel):
    score: int
    correct_points: list[str]
    missing_points: list[str]
    misconceptions: list[str]
    correction_flashcard_id: str | None = None


class SectionStabilityItem(BaseModel):
    section_heading: str | None
    avg_stability: float
    card_count: int


class CardStabilityItem(BaseModel):
    card_id: str
    stability: float
    due_date: str | None


class StudyStatsResponse(BaseModel):
    total_cards: int
    cards_mastered: int
    avg_retention: float
    current_streak: int
    total_study_time_minutes: float
    per_section_stability: list[SectionStabilityItem]
    all_card_stabilities: list[CardStabilityItem]


class DailyHistoryItem(BaseModel):
    date: str  # YYYY-MM-DD
    cards_reviewed: int
    study_time_minutes: float


class StrugglingCardItem(BaseModel):
    flashcard_id: str
    document_id: str | None
    question: str
    again_count: int
    source_section_id: str | None


class SessionCardResponse(BaseModel):
    card_id: str
    question: str
    answer: str
    cards_remaining: int


class SessionStartResponse(BaseModel):
    card_id: str
    question: str
    answer: str
    cards_remaining: int


class SessionReviewRequest(BaseModel):
    card_id: str
    rating: int  # 1=again 2=hard 3=good 4=easy


class SessionReviewResponse(BaseModel):
    done: bool
    next_card: SessionCardResponse | None = None


_RATING_INT_MAP: dict[int, str] = {1: "again", 2: "hard", 3: "good", 4: "easy"}


# ---------------------------------------------------------------------------
# Session plan models and pure builder
# ---------------------------------------------------------------------------


class SessionPlanItem(BaseModel):
    type: Literal["review", "gap", "read"]
    title: str
    minutes: int
    action_label: str
    action_target: str


class SessionPlanResponse(BaseModel):
    total_minutes: int
    items: list[SessionPlanItem]


def _build_session_plan(
    due_count: int,
    gap_areas: list[str],
    recent_doc_titles: list[tuple[str, str]],
    budget_minutes: int,
) -> list[SessionPlanItem]:
    """Assemble a prioritized study agenda from available data.

    Pure function -- no I/O. All inputs are explicit parameters.
    """
    items: list[SessionPlanItem] = []

    if due_count > 0:
        items.append(
            SessionPlanItem(
                type="review",
                title=f"{due_count} flashcards due for review",
                minutes=min(10, max(5, due_count // 2)),
                action_label="Start Review",
                action_target="/study",
            )
        )

    for gap_area in gap_areas[:2]:
        items.append(
            SessionPlanItem(
                type="gap",
                title=f"Weak area: {gap_area}",
                minutes=5,
                action_label="Study Gaps",
                action_target="/study",
            )
        )

    if recent_doc_titles:
        doc_id, doc_title = recent_doc_titles[0]
        items.append(
            SessionPlanItem(
                type="read",
                title=f"Continue: {doc_title}",
                minutes=5,
                action_label="Open Document",
                action_target=f"/learning?document_id={doc_id}",
            )
        )

    return items[:5]


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
    now = datetime.now(UTC)
    stmt = select(FlashcardModel).where(FlashcardModel.due_date <= now)
    if document_id:
        stmt = stmt.where(FlashcardModel.document_id == document_id)
    stmt = stmt.order_by(FlashcardModel.due_date.asc()).limit(limit)
    result = await session.execute(stmt)
    cards = result.scalars().all()
    return [_to_response(c) for c in cards]


@router.get("/session-plan", response_model=SessionPlanResponse)
async def get_session_plan(
    minutes: int = Query(default=20, ge=5, le=120),
    session: AsyncSession = Depends(get_db),
) -> SessionPlanResponse:
    """Return a prioritized study agenda for the given time budget.

    DB-only -- no LLM. Due count, gap areas, and recent docs assembled
    and passed to the pure _build_session_plan() function.
    """
    now = datetime.now(UTC)

    # (a) Count all due flashcards (no document filter)
    due_stmt = select(FlashcardModel).where(FlashcardModel.due_date <= now)
    due_result = await session.execute(due_stmt)
    due_count = len(due_result.scalars().all())

    # (b) Fetch gap area titles across all documents (max 2 distinct non-null headings)
    weak_stmt = (
        select(FlashcardModel)
        .where(FlashcardModel.fsrs_stability < _GAP_STABILITY_THRESHOLD)
        .where(FlashcardModel.reps > _GAP_MIN_REPS)
    )
    weak_result = await session.execute(weak_stmt)
    weak_cards = list(weak_result.scalars().all())

    gap_area_titles: list[str] = []
    if weak_cards:
        chunk_ids = [c.chunk_id for c in weak_cards]
        chunk_stmt = (
            select(ChunkModel, SectionModel.heading)
            .outerjoin(SectionModel, ChunkModel.section_id == SectionModel.id)
            .where(ChunkModel.id.in_(chunk_ids))
        )
        chunk_rows = await session.execute(chunk_stmt)
        seen: set[str] = set()
        for _chunk, heading in chunk_rows:
            if heading and heading not in seen and len(gap_area_titles) < 2:
                seen.add(heading)
                gap_area_titles.append(heading)

    # (c) Fetch recently accessed complete documents
    docs_stmt = (
        select(DocumentModel)
        .where(DocumentModel.stage == "complete")
        .order_by(DocumentModel.last_accessed_at.desc())
        .limit(3)
    )
    docs_result = await session.execute(docs_stmt)
    docs = docs_result.scalars().all()
    recent_docs = [(d.id, d.title) for d in docs]

    items = _build_session_plan(due_count, gap_area_titles, recent_docs, minutes)
    logger.debug(
        "session-plan assembled: due=%d gaps=%d docs=%d items=%d",
        due_count,
        len(gap_area_titles),
        len(recent_docs),
        len(items),
    )
    return SessionPlanResponse(total_minutes=minutes, items=items)


@router.get("/gaps/{document_id}", response_model=list[GapResult])
async def get_gaps(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[GapResult]:
    """Return sections with weak (seen but fragile) flashcards, ordered by avg stability."""
    weak_stmt = (
        select(FlashcardModel)
        .where(FlashcardModel.document_id == document_id)
        .where(FlashcardModel.fsrs_stability < _GAP_STABILITY_THRESHOLD)
        .where(FlashcardModel.reps > _GAP_MIN_REPS)
    )
    weak_result = await session.execute(weak_stmt)
    weak_cards = list(weak_result.scalars().all())

    if not weak_cards:
        return []

    chunk_ids = [c.chunk_id for c in weak_cards]
    chunk_stmt = select(ChunkModel, SectionModel.heading).outerjoin(
        SectionModel, ChunkModel.section_id == SectionModel.id
    ).where(ChunkModel.id.in_(chunk_ids))
    chunk_rows = await session.execute(chunk_stmt)

    chunk_to_section: dict[str, str | None] = {
        chunk.id: heading for chunk, heading in chunk_rows
    }

    return _compute_gaps(weak_cards, chunk_to_section)


@router.post("/sessions/start", response_model=SessionResponse, status_code=201)
async def start_session(
    req: StartSessionRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Create a new study session row and return its ID."""
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        started_at=datetime.now(UTC),
        cards_reviewed=0,
        cards_correct=0,
        mode=req.mode,
    )
    session.add(sess)
    await session.commit()
    await session.refresh(sess)
    logger.info(
        "Study session started",
        extra={"session_id": sess.id, "document_id": req.document_id},
    )
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
    accuracy_pct = round(cards_correct / cards_reviewed * 100, 1) if cards_reviewed > 0 else 0.0

    sess.ended_at = datetime.now(UTC)
    sess.cards_reviewed = cards_reviewed
    sess.cards_correct = cards_correct
    sess.accuracy_pct = accuracy_pct
    await db.commit()
    await db.refresh(sess)

    logger.info(
        "Study session ended",
        extra={
            "session_id": session_id,
            "cards_reviewed": cards_reviewed,
            "cards_correct": cards_correct,
            "accuracy_pct": accuracy_pct,
        },
    )
    return SessionSummary(
        session_id=sess.id,
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        accuracy_pct=accuracy_pct,
        ended_at=sess.ended_at,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    document_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Return a paginated list of study sessions sorted by started_at desc."""
    base_stmt = select(StudySessionModel)
    if document_id:
        base_stmt = base_stmt.where(StudySessionModel.document_id == document_id)

    count_result = await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    sessions_result = await db.execute(
        base_stmt.order_by(StudySessionModel.started_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    sessions = sessions_result.scalars().all()

    # Collect unique doc IDs to fetch titles in one query
    doc_ids = {s.document_id for s in sessions if s.document_id}
    doc_titles: dict[str, str] = {}
    if doc_ids:
        docs_result = await db.execute(
            select(DocumentModel).where(DocumentModel.id.in_(doc_ids))
        )
        for doc in docs_result.scalars().all():
            doc_titles[doc.id] = doc.title

    items: list[SessionListItem] = []
    for sess in sessions:
        duration: float | None = None
        if sess.ended_at:
            duration = round(
                (sess.ended_at - sess.started_at).total_seconds() / 60, 2
            )
        items.append(
            SessionListItem(
                id=sess.id,
                started_at=sess.started_at,
                ended_at=sess.ended_at,
                duration_minutes=duration,
                cards_reviewed=sess.cards_reviewed,
                cards_correct=sess.cards_correct,
                accuracy_pct=sess.accuracy_pct,
                document_id=sess.document_id,
                document_title=doc_titles.get(sess.document_id) if sess.document_id else None,
                mode=sess.mode,
            )
        )

    logger.debug("list_sessions: page=%d page_size=%d total=%d", page, page_size, total)
    return SessionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/sessions/{session_id}/cards", response_model=list[SessionCardDetail])
async def get_session_cards(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[SessionCardDetail]:
    """Return per-card rating and correctness for a given session."""
    sess_result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    if sess_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events_result = await db.execute(
        select(ReviewEventModel, FlashcardModel)
        .join(FlashcardModel, ReviewEventModel.flashcard_id == FlashcardModel.id)
        .where(ReviewEventModel.session_id == session_id)
        .order_by(ReviewEventModel.reviewed_at)
    )
    rows = events_result.all()

    return [
        SessionCardDetail(
            flashcard_id=event.flashcard_id,
            question=card.question,
            rating=event.rating,
            is_correct=event.is_correct,
            reviewed_at=event.reviewed_at,
        )
        for event, card in rows
    ]


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


@router.get("/stats/{document_id}", response_model=StudyStatsResponse)
async def get_study_stats(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> StudyStatsResponse:
    """Return progress statistics for a document."""
    now = datetime.now(UTC)

    # --- All flashcards for the document ---
    cards_result = await db.execute(
        select(FlashcardModel).where(FlashcardModel.document_id == document_id)
    )
    all_cards = cards_result.scalars().all()
    total_cards = len(all_cards)

    # --- Mastered cards ---
    cards_mastered = sum(
        1
        for c in all_cards
        if c.fsrs_state == "review" and c.fsrs_stability > 10.0
    )

    # --- Average retention: e^(-t/S) for reviewed cards ---
    retention_values: list[float] = []
    for c in all_cards:
        if c.last_review and c.fsrs_stability > 0:
            last_review_aware = c.last_review.replace(tzinfo=UTC)
            days_since = (now - last_review_aware).total_seconds() / 86400
            retention_values.append(math.exp(-days_since / c.fsrs_stability))
    avg_retention = (
        round(sum(retention_values) / len(retention_values), 4)
        if retention_values
        else 0.0
    )

    # --- Study sessions for this document ---
    sessions_result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.document_id == document_id)
    )
    sessions = sessions_result.scalars().all()

    # --- Total study time (minutes) ---
    total_study_time_minutes = sum(
        (s.ended_at.replace(tzinfo=UTC) - s.started_at.replace(tzinfo=UTC)).total_seconds() / 60
        for s in sessions
        if s.ended_at
    )

    # --- Current streak (consecutive days with a session, ending today/yesterday) ---
    completed_dates: set[date] = {
        s.started_at.date() for s in sessions
    }
    streak = 0
    check_date = now.date()
    # Allow streak if today or yesterday has a session
    if check_date not in completed_dates:
        check_date = check_date - timedelta(days=1)
    while check_date in completed_dates:
        streak += 1
        check_date -= timedelta(days=1)
    current_streak = streak

    # --- Per-section stability ---
    chunk_ids = [c.chunk_id for c in all_cards]
    per_section: list[SectionStabilityItem] = []
    if chunk_ids:
        chunk_stmt = (
            select(ChunkModel, SectionModel.heading)
            .outerjoin(SectionModel, ChunkModel.section_id == SectionModel.id)
            .where(ChunkModel.id.in_(chunk_ids))
        )
        chunk_rows = await db.execute(chunk_stmt)
        chunk_to_heading: dict[str, str | None] = {}
        for chunk, heading in chunk_rows:
            chunk_to_heading[chunk.id] = heading

        section_groups: dict[str | None, list[FlashcardModel]] = {}
        for c in all_cards:
            heading = chunk_to_heading.get(c.chunk_id)
            section_groups.setdefault(heading, []).append(c)

        for heading, group in section_groups.items():
            avg_stab = sum(c.fsrs_stability for c in group) / len(group)
            per_section.append(
                SectionStabilityItem(
                    section_heading=heading,
                    avg_stability=round(avg_stab, 4),
                    card_count=len(group),
                )
            )
        per_section.sort(key=lambda x: x.avg_stability)

    # --- All card stabilities ---
    all_card_stabilities = [
        CardStabilityItem(
            card_id=c.id,
            stability=round(c.fsrs_stability, 4),
            due_date=c.due_date.isoformat() if c.due_date else None,
        )
        for c in all_cards
    ]

    return StudyStatsResponse(
        total_cards=total_cards,
        cards_mastered=cards_mastered,
        avg_retention=avg_retention,
        current_streak=current_streak,
        total_study_time_minutes=round(total_study_time_minutes, 2),
        per_section_stability=per_section,
        all_card_stabilities=all_card_stabilities,
    )


@router.get("/history", response_model=list[DailyHistoryItem])
async def get_study_history(
    document_id: str | None = None,
    days: int = 90,
    db: AsyncSession = Depends(get_db),
) -> list[DailyHistoryItem]:
    """Return daily study activity for the last N days."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = select(StudySessionModel).where(
        StudySessionModel.started_at >= cutoff,
        StudySessionModel.ended_at.is_not(None),
    )
    if document_id:
        stmt = stmt.where(StudySessionModel.document_id == document_id)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Group by date
    daily: dict[date, dict] = {}
    for s in sessions:
        if not s.ended_at:
            continue
        d = s.started_at.date()
        if d not in daily:
            daily[d] = {"cards_reviewed": 0, "study_time_minutes": 0.0}
        daily[d]["cards_reviewed"] += s.cards_reviewed
        daily[d]["study_time_minutes"] += (
            (s.ended_at - s.started_at).total_seconds() / 60
        )

    return [
        DailyHistoryItem(
            date=d.isoformat(),
            cards_reviewed=v["cards_reviewed"],
            study_time_minutes=round(v["study_time_minutes"], 2),
        )
        for d, v in sorted(daily.items())
    ]


@router.get("/struggling", response_model=list[StrugglingCardItem])
async def get_struggling_cards(
    document_id: str | None = None,
    again_threshold: int = Query(default=3, ge=1),
    days: int = Query(default=14, ge=1, le=365),
    session: AsyncSession = Depends(get_db),
) -> list[StrugglingCardItem]:
    """Return flashcards rated 'again' at least again_threshold times in the last N days."""
    fsrs_svc = get_fsrs_service()
    rows = await fsrs_svc.get_struggling_cards(
        session=session,
        document_id=document_id,
        again_threshold=again_threshold,
        days=days,
    )
    return [StrugglingCardItem(**r) for r in rows]


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
        due_date=datetime.now(UTC),
        reps=0,
        lapses=0,
    )
    session.add(correction)
    return new_id


# ---------------------------------------------------------------------------
# Lightweight session API (stateless start + review)
# ---------------------------------------------------------------------------

async def _get_due_for_session(
    document_id: str, session: AsyncSession
) -> list[FlashcardModel]:
    """Return all due-or-new flashcards for a document, ordered by due_date."""
    now = datetime.now(UTC)
    stmt = (
        select(FlashcardModel)
        .where(
            FlashcardModel.document_id == document_id,
            or_(FlashcardModel.due_date <= now, FlashcardModel.due_date.is_(None)),
        )
        .order_by(FlashcardModel.due_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/session/{document_id}/start", response_model=SessionStartResponse)
async def session_start(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SessionStartResponse:
    """Return the first due/new flashcard for a document and the total remaining count."""
    cards = await _get_due_for_session(document_id, session)
    if not cards:
        raise HTTPException(status_code=404, detail="No flashcards due for this document")
    first = cards[0]
    return SessionStartResponse(
        card_id=first.id,
        question=first.question,
        answer=first.answer,
        cards_remaining=len(cards),
    )


@router.post("/session/{document_id}/review", response_model=SessionReviewResponse)
async def session_review(
    document_id: str,
    req: SessionReviewRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionReviewResponse:
    """Apply FSRS rating to a card, then return the next due card or done=true."""
    if req.rating not in _RATING_INT_MAP:
        raise HTTPException(status_code=422, detail="rating must be 1–4")
    rating_str = _RATING_INT_MAP[req.rating]

    fsrs_svc = get_fsrs_service()
    try:
        await fsrs_svc.schedule(req.card_id, rating_str, session)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    remaining = await _get_due_for_session(document_id, session)
    if not remaining:
        return SessionReviewResponse(done=True)
    first = remaining[0]
    return SessionReviewResponse(
        done=False,
        next_card=SessionCardResponse(
            card_id=first.id,
            question=first.question,
            answer=first.answer,
            cards_remaining=len(remaining),
        ),
    )
