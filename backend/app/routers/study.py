"""Study session endpoints.

Routes:
  GET  /study/due                    — flashcards due for review (due_date <= now)
  POST /study/sessions/start         — create a new study session
  POST /study/sessions/{id}/end      — close a session and return summary
  GET  /study/gaps/{document_id}     — weak flashcard areas grouped by section
  POST /study/teachback              — LLM evaluation of user's teach-back explanation (sync)
  POST /study/teachback/async        — submit teach-back for background evaluation
  GET  /study/teachback/results      — batch-poll teach-back results by IDs
  GET  /study/stats/{document_id}    — progress stats: mastery, retention, streak
  GET  /study/history                — daily study activity for the last N days
  GET  /study/struggling             — cards with >= N 'again' ratings in last M days
"""

import asyncio
import json
import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_session_factory
from app.models import (
    ChunkModel,
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    FlashcardModel,
    MisconceptionModel,
    NoteModel,
    NoteTagIndexModel,
    ReviewEventModel,
    SectionModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.routers.flashcards import FlashcardResponse, _to_response
from app.services.fsrs_service import get_fsrs_service
from app.services.llm import get_llm_service
from app.services.study_path_service import StudyPathService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/study", tags=["study"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAP_STABILITY_THRESHOLD = 2.0
_GAP_MIN_REPS = 1

# Background task set -- strong refs prevent GC (same pattern as feynman_service.py)
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

# Serialize background teachback evaluations to avoid SQLite "database is locked"
# when multiple concurrent tasks try to write (invariant I-1).
_teachback_eval_sem = asyncio.Semaphore(1)


def _fire_and_forget(coro) -> None:  # type: ignore[no-untyped-def]
    """Schedule coroutine as fire-and-forget background task with strong ref."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

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

# S156: rubric evaluation prompts (duplicated in feynman_service.py -- same layer)
_RUBRIC_SYSTEM = (
    "You are an expert tutor evaluating a student explanation. "
    "Output a JSON object only -- no preamble, no markdown fences."
)

_RUBRIC_USER_TMPL = (
    "Source material:\n{source_context}\n\n"
    "Student explanation:\n{explanation}\n\n"
    "Evaluate on three dimensions. "
    "For accuracy: score 0-100 and quote specific evidence from the source. "
    "For completeness: score 0-100 and list missed_points as short concept phrases. "
    "For clarity: score 0-100 and give a one-sentence comment. "
    'Output JSON: {{"accuracy": {{"score": int, "evidence": str}}, '
    '"completeness": {{"score": int, "missed_points": [str]}}, '
    '"clarity": {{"score": int, "evidence": str}}}}'
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    document_id: str | None = None
    collection_id: str | None = None
    mode: str = "flashcard"


class SessionResponse(BaseModel):
    id: str
    document_id: str | None
    collection_id: str | None = None
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
    collection_id: str | None = None
    collection_name: str | None = None
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
    session_id: str | None = None


class RubricDimensionResponse(BaseModel):
    score: int
    evidence: str


class RubricCompletenessResponse(BaseModel):
    score: int
    missed_points: list[str]


class TeachbackRubricResponse(BaseModel):
    accuracy: RubricDimensionResponse
    completeness: RubricCompletenessResponse
    clarity: RubricDimensionResponse


class TeachbackResponse(BaseModel):
    score: int
    correct_points: list[str]
    missing_points: list[str]
    misconceptions: list[str]
    correction_flashcard_id: str | None = None
    rubric: TeachbackRubricResponse | None = None  # S156: null when rubric LLM call fails


class TeachbackSubmitResponse(BaseModel):
    """Returned by POST /study/teachback/async -- evaluation runs in background."""

    id: str


class TeachbackResultItem(BaseModel):
    """Single item in batch-poll response."""

    id: str
    status: str  # "pending" | "complete" | "error"
    flashcard_id: str
    question: str = ""
    score: int | None = None
    correct_points: list[str] = []
    missing_points: list[str] = []
    misconceptions: list[str] = []
    correction_flashcard_id: str | None = None
    rubric: TeachbackRubricResponse | None = None
    user_explanation: str | None = None


class TeachbackResultsBatchResponse(BaseModel):
    results: list[TeachbackResultItem]


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
    due_today: int
    new_today: int
    mastery_pct: float
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


class SectionHeatmapItem(BaseModel):
    section_id: str
    fragility_score: float | None
    due_card_count: int
    avg_retention_pct: float | None


class SectionHeatmapResponse(BaseModel):
    heatmap: dict[str, SectionHeatmapItem]


class DueCountResponse(BaseModel):
    due_today: int


class CollectionTopic(BaseModel):
    tag: str
    card_count: int
    note_count: int


class CollectionSource(BaseModel):
    id: str
    title: str
    type: str  # "document" | "note"


class CollectionSubEnclave(BaseModel):
    id: str
    name: str
    card_count: int


class StudyCollectionDashboardResponse(BaseModel):
    collection_id: str
    collection_name: str
    due_today: int
    new_today: int
    mastery_pct: float
    topics: list[CollectionTopic]
    sources: list[CollectionSource]
    sub_collections: list[CollectionSubEnclave] = []


def _compute_section_heatmap(
    cards: list[FlashcardModel],
    chunk_to_section: dict[str, str | None],
    now: datetime,
) -> dict[str, SectionHeatmapItem]:
    """Aggregate FSRS retrievability per section.

    fragility_score = 1 - avg_retrievability where retrievability = exp(-t/S).
    Sections with no cards are absent from the returned dict.
    Pure function -- no I/O.
    """
    groups: dict[str, list[FlashcardModel]] = {}
    for card in cards:
        if not card.chunk_id:
            continue
        section_id = chunk_to_section.get(card.chunk_id)
        if section_id is None:
            continue
        groups.setdefault(section_id, []).append(card)

    result: dict[str, SectionHeatmapItem] = {}
    for section_id, group in groups.items():
        retrievabilities: list[float] = []
        for card in group:
            if card.fsrs_stability <= 0 or card.last_review is None:
                retrievabilities.append(0.0)
            else:
                last_review_aware = card.last_review.replace(tzinfo=UTC)
                days_since = (now - last_review_aware).total_seconds() / 86400
                retrievabilities.append(math.exp(-days_since / card.fsrs_stability))

        avg_ret = sum(retrievabilities) / len(retrievabilities)
        fragility = round(max(0.0, min(1.0, 1.0 - avg_ret)), 4)
        due_count = sum(
            1 for card in group if card.due_date and card.due_date.replace(tzinfo=UTC) <= now
        )
        result[section_id] = SectionHeatmapItem(
            section_id=section_id,
            fragility_score=fragility,
            due_card_count=due_count,
            avg_retention_pct=round(avg_ret * 100, 1),
        )
    return result


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


@router.get("/due-count", response_model=DueCountResponse)
async def get_due_count(
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    document_ids: list[str] | None = Query(default=None),
    note_ids: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> DueCountResponse:
    """Return the count of flashcards whose due_date is today or in the past."""
    now = datetime.now(UTC)
    stmt = select(func.count()).select_from(FlashcardModel).where(FlashcardModel.due_date <= now)

    # Apply filters
    if document_ids:
        stmt = stmt.where(FlashcardModel.document_id.in_(document_ids))
    if note_ids:
        stmt = stmt.where(FlashcardModel.note_id.in_(note_ids))

    # Combined collection logic
    if collection_id and not (document_ids or note_ids):
        # Resolve all doc/note IDs in hierarchy
        c_doc_ids, c_note_ids = await _resolve_collection_members(collection_id, session)

        if tag:
            # Topic filter within collection
            from app.routers.documents import _safe_tags

            all_c_docs = (
                await session.execute(
                    select(DocumentModel.id, DocumentModel.tags).where(
                        DocumentModel.id.in_(c_doc_ids)
                    )
                )
            ).all()
            matching_doc_ids = [did for did, dtags in all_c_docs if tag in _safe_tags(dtags)]

            tag_notes_stmt = (
                select(NoteTagIndexModel.note_id)
                .where(NoteTagIndexModel.note_id.in_(c_note_ids))
                .where(NoteTagIndexModel.tag_full == tag)
            )
            matching_note_ids = (await session.execute(tag_notes_stmt)).scalars().all()

            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    FlashcardModel.note_id.in_(matching_note_ids) if matching_note_ids else False,
                )
            )
        else:
            # All in collection
            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(c_doc_ids) if c_doc_ids else False,
                    FlashcardModel.note_id.in_(c_note_ids) if c_note_ids else False,
                )
            )
    elif tag:
        # Global tag filter (no collection scope)
        all_docs_with_tag = (
            await session.execute(select(DocumentModel.id, DocumentModel.tags))
        ).all()
        from app.routers.documents import _safe_tags

        matching_doc_ids = [did for did, dtags in all_docs_with_tag if tag in _safe_tags(dtags)]

        stmt = (
            stmt.join(NoteModel, FlashcardModel.note_id == NoteModel.id, isouter=True)
            .join(NoteTagIndexModel, NoteModel.id == NoteTagIndexModel.note_id, isouter=True)
            .where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    NoteTagIndexModel.tag_full == tag,
                )
            )
        )

    result = await session.execute(stmt)
    count = result.scalar_one()
    logger.debug("due-count: %d cards due", count)
    return DueCountResponse(due_today=count)


@router.get("/due", response_model=list[FlashcardResponse])
async def get_due_cards(
    document_id: str | None = None,
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    document_ids: list[str] | None = Query(default=None),
    note_ids: list[str] | None = Query(default=None),
    limit: int = 20,
    session: AsyncSession = Depends(get_db),
) -> list[FlashcardResponse]:
    """Return flashcards whose due_date is now or in the past."""
    now = datetime.now(UTC)
    stmt = select(FlashcardModel).where(FlashcardModel.due_date <= now)

    # Apply filters
    used_document_ids = document_ids or ([document_id] if document_id else [])
    if used_document_ids:
        stmt = stmt.where(FlashcardModel.document_id.in_(used_document_ids))
    if note_ids:
        stmt = stmt.where(FlashcardModel.note_id.in_(note_ids))

    if collection_id and not (used_document_ids or note_ids):
        # Resolve all doc/note IDs in hierarchy
        c_doc_ids, c_note_ids = await _resolve_collection_members(collection_id, session)

        if tag:
            from app.routers.documents import _safe_tags

            all_c_docs = (
                await session.execute(
                    select(DocumentModel.id, DocumentModel.tags).where(
                        DocumentModel.id.in_(c_doc_ids)
                    )
                )
            ).all()
            matching_doc_ids = [did for did, dtags in all_c_docs if tag in _safe_tags(dtags)]

            tag_notes_stmt = (
                select(NoteTagIndexModel.note_id)
                .where(NoteTagIndexModel.note_id.in_(c_note_ids))
                .where(NoteTagIndexModel.tag_full == tag)
            )
            matching_note_ids = (await session.execute(tag_notes_stmt)).scalars().all()

            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    FlashcardModel.note_id.in_(matching_note_ids) if matching_note_ids else False,
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(c_doc_ids) if c_doc_ids else False,
                    FlashcardModel.note_id.in_(c_note_ids) if c_note_ids else False,
                )
            )
    elif tag:
        all_docs_with_tag = (
            await session.execute(select(DocumentModel.id, DocumentModel.tags))
        ).all()
        from app.routers.documents import _safe_tags

        matching_doc_ids = [did for did, dtags in all_docs_with_tag if tag in _safe_tags(dtags)]

        stmt = (
            stmt.join(NoteModel, FlashcardModel.note_id == NoteModel.id, isouter=True)
            .join(NoteTagIndexModel, NoteModel.id == NoteTagIndexModel.note_id, isouter=True)
            .where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    NoteTagIndexModel.tag_full == tag,
                )
            )
        )

    stmt = stmt.order_by(FlashcardModel.due_date.asc()).limit(limit)
    result = await session.execute(stmt)
    cards = list(result.scalars().all())

    # Build chunk_id -> section_id map for S138 SourcePanel
    chunk_ids = [c.chunk_id for c in cards if c.chunk_id]
    chunk_to_section: dict[str, str | None] = {}
    if chunk_ids:
        chunk_result = await session.execute(
            select(ChunkModel.id, ChunkModel.section_id).where(ChunkModel.id.in_(chunk_ids))
        )
        for cid, sid in chunk_result:
            chunk_to_section[cid] = sid

    return [_to_response(c, section_id=chunk_to_section.get(c.chunk_id or "")) for c in cards]


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
    chunk_stmt = (
        select(ChunkModel, SectionModel.heading)
        .outerjoin(SectionModel, ChunkModel.section_id == SectionModel.id)
        .where(ChunkModel.id.in_(chunk_ids))
    )
    chunk_rows = await session.execute(chunk_stmt)

    chunk_to_section: dict[str, str | None] = {chunk.id: heading for chunk, heading in chunk_rows}

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
        collection_id=req.collection_id,
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
        extra={
            "session_id": sess.id,
            "document_id": req.document_id,
            "collection_id": req.collection_id,
            "mode": req.mode,
        },
    )
    return SessionResponse.model_validate(sess)


@router.post("/sessions/{session_id}/end", response_model=SessionSummary)
async def end_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> SessionSummary:
    """Close a study session, tally review events, and return the summary."""
    result = await db.execute(select(StudySessionModel).where(StudySessionModel.id == session_id))
    sess = result.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events_result = await db.execute(
        select(ReviewEventModel).where(ReviewEventModel.session_id == session_id)
    )
    events = events_result.scalars().all()

    # Check for teachback results -- use average score instead of binary pass/fail
    tb_result = await db.execute(
        select(TeachbackResultModel).where(
            TeachbackResultModel.session_id == session_id,
            TeachbackResultModel.status == "complete",
        )
    )
    tb_rows = tb_result.scalars().all()

    if tb_rows:
        scores = [tb.score for tb in tb_rows if tb.score is not None]
        cards_reviewed = len(tb_rows)
        cards_correct = sum(1 for s in scores if s >= 60)
        accuracy_pct = round(sum(scores) / len(scores), 1) if scores else 0.0
    else:
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


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a study session and all associated review events and teachback results."""
    result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    sess = result.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.execute(
        sa_delete(ReviewEventModel).where(ReviewEventModel.session_id == session_id)
    )
    await db.execute(
        sa_delete(TeachbackResultModel).where(
            TeachbackResultModel.session_id == session_id
        )
    )
    await db.delete(sess)
    await db.commit()
    logger.info("Study session deleted", extra={"session_id": session_id})


async def _resolve_collection_members(
    collection_id: str, session: AsyncSession
) -> tuple[list[str], list[str]]:
    """Recursively identify all document and note IDs in a collection hierarchy."""
    # 1. Resolve all collection IDs in the hierarchy
    all_coll_ids = {collection_id}
    to_process = [collection_id]

    while to_process:
        curr_id = to_process.pop()
        children_stmt = select(CollectionModel.id).where(
            CollectionModel.parent_collection_id == curr_id
        )
        children = (await session.execute(children_stmt)).scalars().all()
        for child_id in children:
            if child_id not in all_coll_ids:
                all_coll_ids.add(child_id)
                to_process.append(child_id)

    # 2. Get members of all identified collections
    members_stmt = select(CollectionMemberModel.member_id, CollectionMemberModel.member_type).where(
        CollectionMemberModel.collection_id.in_(list(all_coll_ids))
    )
    members_rows = (await session.execute(members_stmt)).all()

    doc_ids = list({m[0] for m in members_rows if m[1] == "document"})
    note_ids = list({m[0] for m in members_rows if m[1] == "note"})
    return doc_ids, note_ids


@router.get(
    "/collections/{collection_id}/dashboard", response_model=StudyCollectionDashboardResponse
)
async def get_collection_study_dashboard(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> StudyCollectionDashboardResponse:
    """Return a summary of study status for all material in a collection (S192)."""
    # 1. Fetch collection name
    coll_result = await session.execute(
        select(CollectionModel.name).where(CollectionModel.id == collection_id)
    )
    coll_name = coll_result.scalar_one_or_none()
    if not coll_name:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 2. Resolve all documents and notes in this hierarchy
    doc_ids, note_ids = await _resolve_collection_members(collection_id, session)

    # 3. Aggregate flashcard stats across all documents (and any note-sourced cards)
    now = datetime.now(UTC)
    cards_stmt = select(FlashcardModel).where(
        or_(
            FlashcardModel.document_id.in_(doc_ids) if doc_ids else False,
            FlashcardModel.note_id.in_(note_ids) if note_ids else False,
        )
    )
    cards_result = await session.execute(cards_stmt)
    all_cards = list(cards_result.scalars().all())

    due_today = sum(1 for c in all_cards if c.due_date and c.due_date.replace(tzinfo=UTC) <= now)
    new_today = sum(1 for c in all_cards if c.fsrs_state == "new")

    # Mastery % = cards with stability > 30 days
    mastered = sum(1 for c in all_cards if c.fsrs_stability > 30.0)
    mastery_pct = round(mastered / len(all_cards) * 100, 1) if all_cards else 0.0

    # 4. Topics (tags) aggregation
    # We want tags that are present in either documents or notes of this collection.
    # For each tag, we want:
    # - card_count: flashcards linked to docs with this tag OR notes with this tag
    #   (within the collection)
    # - note_count: notes in the collection with this tag

    tag_to_docs: dict[str, set[str]] = {}
    tag_to_notes: dict[str, set[str]] = {}

    # (a) Process documents in collection
    if doc_ids:
        docs_stmt = select(DocumentModel.id, DocumentModel.tags).where(
            DocumentModel.id.in_(doc_ids)
        )
        docs_rows = (await session.execute(docs_stmt)).all()
        for did, dtags in docs_rows:
            from app.routers.documents import _safe_tags

            dtags_list = _safe_tags(dtags)
            for t in dtags_list:
                tag_to_docs.setdefault(t, set()).add(did)

    # (b) Process notes in collection
    if note_ids:
        note_tag_stmt = select(NoteTagIndexModel.tag_full, NoteTagIndexModel.note_id).where(
            NoteTagIndexModel.note_id.in_(note_ids)
        )
        note_tag_rows = (await session.execute(note_tag_stmt)).all()
        for t, nid in note_tag_rows:
            tag_to_notes.setdefault(t, set()).add(nid)

    # (c) Build topics list
    all_tags = set(tag_to_docs.keys()) | set(tag_to_notes.keys())
    topics: list[CollectionTopic] = []

    for t in all_tags:
        t_doc_ids = list(tag_to_docs.get(t, set()))
        t_note_ids = list(tag_to_notes.get(t, set()))

        # Count flashcards for this tag in this collection
        # Card belongs if: (doc in t_doc_ids) OR (note in t_note_ids)
        card_count_stmt = select(func.count(FlashcardModel.id)).where(
            or_(
                FlashcardModel.document_id.in_(t_doc_ids) if t_doc_ids else False,
                FlashcardModel.note_id.in_(t_note_ids) if t_note_ids else False,
            )
        )
        card_count = (await session.execute(card_count_stmt)).scalar() or 0

        note_count = len(t_note_ids)
        if card_count > 0 or note_count > 0:
            topics.append(CollectionTopic(tag=t, card_count=card_count, note_count=note_count))

    # Sort by card_count desc, then note_count desc
    topics.sort(key=lambda x: (x.card_count, x.note_count), reverse=True)
    topics = topics[:10]

    # 5. Sources list
    sources: list[CollectionSource] = []
    if doc_ids:
        docs_result = await session.execute(
            select(DocumentModel.id, DocumentModel.title).where(DocumentModel.id.in_(doc_ids))
        )
        for did, dtitle in docs_result:
            sources.append(CollectionSource(id=did, title=dtitle, type="document"))
    if note_ids:
        notes_result = await session.execute(
            select(NoteModel.id, NoteModel.content).where(NoteModel.id.in_(note_ids))
        )
        for nid, ncontent in notes_result:
            ntitle = ncontent.split("\n")[0][:60] or "Untitled Note"
            sources.append(CollectionSource(id=nid, title=ntitle, type="note"))

    # 6. Sub-collections
    child_stmt = select(CollectionModel.id, CollectionModel.name).where(
        CollectionModel.parent_collection_id == collection_id
    )
    children = (await session.execute(child_stmt)).all()
    sub_collections: list[CollectionSubEnclave] = []

    for cid, cname in children:
        # Get total card count for this sub-enclave
        c_doc_ids, c_note_ids = await _resolve_collection_members(cid, session)
        count_stmt = select(func.count(FlashcardModel.id)).where(
            or_(
                FlashcardModel.document_id.in_(c_doc_ids) if c_doc_ids else False,
                FlashcardModel.note_id.in_(c_note_ids) if c_note_ids else False,
            )
        )
        total_cards_count = (await session.execute(count_stmt)).scalar() or 0
        sub_collections.append(
            CollectionSubEnclave(id=cid, name=cname, card_count=total_cards_count)
        )

    return StudyCollectionDashboardResponse(
        collection_id=collection_id,
        collection_name=coll_name,
        due_today=due_today,
        new_today=new_today,
        mastery_pct=mastery_pct,
        topics=topics,
        sources=sources,
        sub_collections=sub_collections,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    document_id: str | None = None,
    collection_id: str | None = Query(
        default=None, description="Filter sessions to a specific collection/enclave"
    ),
    mode: str | None = Query(default=None, description="Filter by mode: flashcard, teachback"),
    status: str | None = Query(
        default=None, description="Filter by status: incomplete (no ended_at), complete"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Return a paginated list of study sessions sorted by started_at desc."""
    base_stmt = select(StudySessionModel)
    if document_id:
        base_stmt = base_stmt.where(StudySessionModel.document_id == document_id)
    if collection_id:
        base_stmt = base_stmt.where(StudySessionModel.collection_id == collection_id)
    if mode:
        base_stmt = base_stmt.where(StudySessionModel.mode == mode)
    if status == "incomplete":
        base_stmt = base_stmt.where(StudySessionModel.ended_at.is_(None))
    elif status == "complete":
        base_stmt = base_stmt.where(StudySessionModel.ended_at.is_not(None))

    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    sessions_result = await db.execute(
        base_stmt.order_by(StudySessionModel.started_at.desc()).offset(offset).limit(page_size)
    )
    sessions = sessions_result.scalars().all()

    # Collect unique doc IDs to fetch titles in one query
    doc_ids = {s.document_id for s in sessions if s.document_id}
    doc_titles: dict[str, str] = {}
    if doc_ids:
        docs_result = await db.execute(select(DocumentModel).where(DocumentModel.id.in_(doc_ids)))
        for doc in docs_result.scalars().all():
            doc_titles[doc.id] = doc.title

    coll_ids = {s.collection_id for s in sessions if s.collection_id}
    coll_names: dict[str, str] = {}
    if coll_ids:
        colls_result = await db.execute(
            select(CollectionModel).where(CollectionModel.id.in_(coll_ids))
        )
        for coll in colls_result.scalars().all():
            coll_names[coll.id] = coll.name

    items: list[SessionListItem] = []
    for sess in sessions:
        duration: float | None = None
        if sess.ended_at:
            duration = round((sess.ended_at - sess.started_at).total_seconds() / 60, 2)
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
                collection_id=sess.collection_id,
                collection_name=coll_names.get(sess.collection_id) if sess.collection_id else None,
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

    # S156: rubric evaluation (second LLM call; graceful fallback on failure)
    rubric_dict: dict | None = None
    try:
        rubric_prompt = _RUBRIC_USER_TMPL.format(
            source_context=card.answer,
            explanation=req.user_explanation,
        )
        raw_rubric = await llm.generate(prompt=rubric_prompt, system=_RUBRIC_SYSTEM)
        rubric_dict = _parse_rubric(raw_rubric)
    except Exception:  # noqa: BLE001 -- never raise 500 from rubric call
        logger.warning("Rubric LLM call failed for flashcard=%s; null rubric", card.id)
        rubric_dict = None

    # Persist teachback result
    tb_result = TeachbackResultModel(
        id=str(uuid.uuid4()),
        flashcard_id=card.id,
        user_explanation=req.user_explanation,
        score=score,
        correct_points=correct_points,
        missing_points=missing_points,
        misconceptions=misconceptions,
        rubric_json=rubric_dict,
    )
    session.add(tb_result)

    correction_card_id: str | None = None

    # If score < 60 and there are misconceptions, create MisconceptionModel rows
    # and a correction flashcard
    if score < 60 and misconceptions:
        # Only persist misconceptions when document_id is set;
        # note-sourced flashcards have document_id=None.
        if card.document_id:
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

    # Build rubric response
    rubric_response: TeachbackRubricResponse | None = None
    if rubric_dict is not None:
        try:
            rubric_response = TeachbackRubricResponse(
                accuracy=RubricDimensionResponse(**rubric_dict["accuracy"]),
                completeness=RubricCompletenessResponse(**rubric_dict["completeness"]),
                clarity=RubricDimensionResponse(**rubric_dict["clarity"]),
            )
        except (KeyError, TypeError, ValueError):
            rubric_response = None

    return TeachbackResponse(
        score=score,
        correct_points=correct_points,
        missing_points=missing_points,
        misconceptions=misconceptions,
        correction_flashcard_id=correction_card_id,
        rubric=rubric_response,
    )


# ---------------------------------------------------------------------------
# Async teach-back: submit + background evaluate + batch poll
# ---------------------------------------------------------------------------


def _score_to_rating(score: int) -> str:
    """Map teach-back score (0-100) to FSRS rating for spaced repetition."""
    if score >= 80:
        return "good"
    if score >= 60:
        return "hard"
    return "again"


async def _evaluate_teachback_bg(
    tb_id: str,
    card_id: str,
    card_answer: str,
    card_document_id: str,
    card_question: str,
    user_explanation: str,
    session_id: str | None = None,
) -> None:
    """Background coroutine: evaluate teach-back and update the row.

    Uses its own DB session (invariant I-1: no shared AsyncSession across tasks).
    After scoring, creates an FSRS review + ReviewEventModel so teach-back
    results feed into spaced repetition and session progress stats.
    """
    logger.info("Teachback bg task started for %s", tb_id)

    # LLM calls happen outside the semaphore so they don't block other evals.
    llm = get_llm_service()

    # LLM call 1: evaluation
    prompt = _TEACHBACK_USER_TMPL.format(
        answer=card_answer,
        explanation=user_explanation,
    )
    raw = await llm.generate(prompt=prompt, system=_TEACHBACK_SYSTEM)
    parsed = _parse_teachback_response(raw)
    score = parsed.get("score", 0)
    correct_points: list[str] = parsed.get("correct_points", [])
    missing_points: list[str] = parsed.get("missing_points", [])
    misconceptions: list[str] = parsed.get("misconceptions", [])

    # LLM call 2: rubric (graceful fallback)
    rubric_dict: dict | None = None
    try:
        rubric_prompt = _RUBRIC_USER_TMPL.format(
            source_context=card_answer,
            explanation=user_explanation,
        )
        raw_rubric = await llm.generate(
            prompt=rubric_prompt, system=_RUBRIC_SYSTEM,
        )
        rubric_dict = _parse_rubric(raw_rubric)
    except Exception:  # noqa: BLE001
        logger.warning("Rubric LLM call failed for teachback=%s", tb_id)

    # Serialize DB writes to avoid SQLite "database is locked" (invariant I-1)
    rating = _score_to_rating(score)
    async with _teachback_eval_sem:
        session_factory = get_session_factory()
        async with session_factory() as session:
            try:
                # Update the pending row
                result = await session.execute(
                    select(TeachbackResultModel).where(
                        TeachbackResultModel.id == tb_id
                    )
                )
                tb_row = result.scalar_one_or_none()
                if tb_row is None:
                    logger.error("Teachback row %s disappeared", tb_id)
                    return

                tb_row.score = score
                tb_row.correct_points = correct_points
                tb_row.missing_points = missing_points
                tb_row.misconceptions = misconceptions
                tb_row.rubric_json = rubric_dict
                tb_row.status = "complete"

                # FSRS review: schedule the card
                fsrs = get_fsrs_service()
                await fsrs.schedule(card_id, rating, session)

                # Create ReviewEventModel so end_session tallies include this card
                if session_id:
                    event = ReviewEventModel(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        flashcard_id=card_id,
                        rating=rating,
                        is_correct=rating != "again",
                    )
                    session.add(event)

                # Misconceptions + correction flashcard
                if score < 60 and misconceptions:
                    card_result = await session.execute(
                        select(FlashcardModel).where(FlashcardModel.id == card_id)
                    )
                    card = card_result.scalar_one_or_none()
                    if card:
                        if card_document_id:
                            for m_text in misconceptions:
                                misconception = MisconceptionModel(
                                    id=str(uuid.uuid4()),
                                    document_id=card_document_id,
                                    flashcard_id=card_id,
                                    user_answer=user_explanation,
                                    error_type="misconception",
                                    correction_note=m_text,
                                )
                                session.add(misconception)
                        await _generate_correction_flashcard(
                            card=card,
                            misconception=misconceptions[0],
                            session=session,
                        )

                await session.commit()
                logger.info(
                    "Teachback bg evaluated",
                    extra={
                        "teachback_id": tb_id,
                        "score": score,
                        "fsrs_rating": rating,
                    },
                )

            except Exception:
                logger.exception(
                    "Teachback background evaluation failed for %s", tb_id
                )
                try:
                    await session.rollback()
                    result = await session.execute(
                        select(TeachbackResultModel).where(
                            TeachbackResultModel.id == tb_id
                        )
                    )
                    tb_row = result.scalar_one_or_none()
                    if tb_row:
                        tb_row.status = "error"
                        await session.commit()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to mark teachback %s as error", tb_id
                    )


@router.post("/teachback/async", response_model=TeachbackSubmitResponse)
async def teachback_async(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackSubmitResponse:
    """Submit teach-back for background evaluation. Returns immediately."""
    # Validate flashcard
    card_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == req.flashcard_id)
    )
    card = card_result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # Ensure the study session is marked as teachback mode
    if req.session_id:
        sess_result = await session.execute(
            select(StudySessionModel).where(
                StudySessionModel.id == req.session_id
            )
        )
        study_sess = sess_result.scalar_one_or_none()
        if study_sess and study_sess.mode != "teachback":
            study_sess.mode = "teachback"

    # Persist pending row
    tb_id = str(uuid.uuid4())
    tb_row = TeachbackResultModel(
        id=tb_id,
        flashcard_id=card.id,
        user_explanation=req.user_explanation,
        score=0,
        correct_points=[],
        missing_points=[],
        misconceptions=[],
        status="pending",
        session_id=req.session_id,
    )
    session.add(tb_row)
    await session.commit()
    logger.info("Teachback async submitted: id=%s flashcard=%s", tb_id, card.id)

    # Fire background evaluation
    _fire_and_forget(
        _evaluate_teachback_bg(
            tb_id=tb_id,
            card_id=card.id,
            card_answer=card.answer,
            card_document_id=card.document_id,
            card_question=card.question,
            user_explanation=req.user_explanation,
            session_id=req.session_id,
        )
    )

    return TeachbackSubmitResponse(id=tb_id)


@router.get("/teachback/results", response_model=TeachbackResultsBatchResponse)
async def get_teachback_results(
    ids: str = Query(..., description="Comma-separated teachback result IDs"),
    session: AsyncSession = Depends(get_db),
) -> TeachbackResultsBatchResponse:
    """Batch-poll teach-back results by IDs."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        return TeachbackResultsBatchResponse(results=[])

    # Fetch results joined with flashcard for question text
    stmt = (
        select(TeachbackResultModel, FlashcardModel.question)
        .join(
            FlashcardModel,
            TeachbackResultModel.flashcard_id == FlashcardModel.id,
            isouter=True,
        )
        .where(TeachbackResultModel.id.in_(id_list))
    )
    rows = (await session.execute(stmt)).all()

    items: list[TeachbackResultItem] = []
    for tb, question in rows:
        rubric_response: TeachbackRubricResponse | None = None
        if tb.status == "complete" and tb.rubric_json is not None:
            try:
                rubric_response = TeachbackRubricResponse(
                    accuracy=RubricDimensionResponse(**tb.rubric_json["accuracy"]),
                    completeness=RubricCompletenessResponse(
                        **tb.rubric_json["completeness"]
                    ),
                    clarity=RubricDimensionResponse(**tb.rubric_json["clarity"]),
                )
            except (KeyError, TypeError, ValueError):
                rubric_response = None

        items.append(
            TeachbackResultItem(
                id=tb.id,
                status=tb.status,
                flashcard_id=tb.flashcard_id,
                question=question or "",
                score=tb.score if tb.status == "complete" else None,
                correct_points=tb.correct_points if tb.status == "complete" else [],
                missing_points=tb.missing_points if tb.status == "complete" else [],
                misconceptions=tb.misconceptions if tb.status == "complete" else [],
                rubric=rubric_response,
                user_explanation=tb.user_explanation if tb.status == "complete" else None,
            )
        )

    return TeachbackResultsBatchResponse(results=items)


@router.get(
    "/sessions/{session_id}/teachback-results",
    response_model=TeachbackResultsBatchResponse,
)
async def get_session_teachback_results(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResultsBatchResponse:
    """Get all teach-back results for a study session."""
    stmt = (
        select(TeachbackResultModel, FlashcardModel.question)
        .join(
            FlashcardModel,
            TeachbackResultModel.flashcard_id == FlashcardModel.id,
            isouter=True,
        )
        .where(TeachbackResultModel.session_id == session_id)
        .order_by(TeachbackResultModel.created_at)
    )
    rows = (await session.execute(stmt)).all()

    items: list[TeachbackResultItem] = []
    for tb, question in rows:
        rubric_response: TeachbackRubricResponse | None = None
        if tb.status == "complete" and tb.rubric_json is not None:
            try:
                rubric_response = TeachbackRubricResponse(
                    accuracy=RubricDimensionResponse(**tb.rubric_json["accuracy"]),
                    completeness=RubricCompletenessResponse(
                        **tb.rubric_json["completeness"]
                    ),
                    clarity=RubricDimensionResponse(**tb.rubric_json["clarity"]),
                )
            except (KeyError, TypeError, ValueError):
                rubric_response = None

        items.append(
            TeachbackResultItem(
                id=tb.id,
                status=tb.status,
                flashcard_id=tb.flashcard_id,
                question=question or "",
                score=tb.score if tb.status == "complete" else None,
                correct_points=tb.correct_points if tb.status == "complete" else [],
                missing_points=tb.missing_points if tb.status == "complete" else [],
                misconceptions=tb.misconceptions if tb.status == "complete" else [],
                rubric=rubric_response,
                user_explanation=tb.user_explanation if tb.status == "complete" else None,
            )
        )

    return TeachbackResultsBatchResponse(results=items)


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
        1 for c in all_cards if c.fsrs_state == "review" and c.fsrs_stability > 30.0
    )
    mastery_pct = round(cards_mastered / total_cards * 100, 1) if total_cards > 0 else 0.0

    # --- Due and New counts ---
    due_today = sum(1 for c in all_cards if c.due_date and c.due_date.replace(tzinfo=UTC) <= now)
    new_today = sum(1 for c in all_cards if c.fsrs_state == "new")

    # --- Average retention: e^(-t/S) for reviewed cards ---
    retention_values: list[float] = []
    for c in all_cards:
        if c.last_review and c.fsrs_stability > 0:
            last_review_aware = c.last_review.replace(tzinfo=UTC)
            days_since = (now - last_review_aware).total_seconds() / 86400
            retention_values.append(math.exp(-days_since / c.fsrs_stability))
    avg_retention = (
        round(sum(retention_values) / len(retention_values), 4) if retention_values else 0.0
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
    completed_dates: set[date] = {s.started_at.date() for s in sessions}
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
        due_today=due_today,
        new_today=new_today,
        mastery_pct=mastery_pct,
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
        daily[d]["study_time_minutes"] += (s.ended_at - s.started_at).total_seconds() / 60

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


@router.get("/section-heatmap", response_model=SectionHeatmapResponse)
async def get_section_heatmap(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SectionHeatmapResponse:
    """Return per-section FSRS fragility scores for a document.

    fragility_score ranges from 0.0 (well-retained) to 1.0 (completely forgotten).
    Sections with no flashcards are absent from the heatmap dict.
    """
    cards_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.document_id == document_id)
    )
    cards = list(cards_result.scalars().all())

    if not cards:
        return SectionHeatmapResponse(heatmap={})

    chunk_ids = [c.chunk_id for c in cards if c.chunk_id]
    chunk_to_section: dict[str, str | None] = {}
    if chunk_ids:
        chunk_rows = await session.execute(
            select(ChunkModel.id, ChunkModel.section_id).where(ChunkModel.id.in_(chunk_ids))
        )
        for chunk_id, section_id in chunk_rows:
            chunk_to_section[chunk_id] = section_id

    now = datetime.now(UTC)
    heatmap = _compute_section_heatmap(cards, chunk_to_section, now)
    logger.info(
        "section-heatmap: document_id=%s sections_with_cards=%d",
        document_id,
        len(heatmap),
    )
    return SectionHeatmapResponse(heatmap=heatmap)


# ---------------------------------------------------------------------------
# Study path endpoints (S139)
# ---------------------------------------------------------------------------


class StudyPathItemResponse(BaseModel):
    concept: str
    mastery: float
    skip: bool
    reason: str
    avg_stability_days: float


class StudyPathAPIResponse(BaseModel):
    concept: str
    document_id: str
    path: list[StudyPathItemResponse]


class StartConceptItemResponse(BaseModel):
    concept: str
    prereq_chain_length: int
    flashcard_count: int
    rationale: str


class StartConceptsAPIResponse(BaseModel):
    document_id: str
    concepts: list[StartConceptItemResponse]


@router.get("/path", response_model=StudyPathAPIResponse)
async def get_study_path(
    document_id: str = Query(...),
    concept: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> StudyPathAPIResponse:
    """Return FSRS-aware prerequisite study path for a concept in a document.

    Path is ordered from earliest prerequisite to the requested concept.
    Each item includes mastery (0-1), skip flag (avg_stability >= 14 days),
    and reason string.

    Returns empty path (not 404) when the concept has no PREREQUISITE_OF edges.
    """
    svc = StudyPathService()
    result = await svc.get_study_path(document_id, concept, session)
    return StudyPathAPIResponse(
        concept=result["concept"],
        document_id=result["document_id"],
        path=[StudyPathItemResponse(**vars(item)) for item in result["path"]],
    )


@router.get("/start", response_model=StartConceptsAPIResponse)
async def get_start_concepts(
    document_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> StartConceptsAPIResponse:
    """Return up to 3 entry-point concepts for a document with highest learning ROI.

    Entry-point concepts are those with no unsatisfied prerequisites.
    Returns empty concepts list (not 404) when no PREREQUISITE_OF edges exist.
    """
    svc = StudyPathService()
    result = await svc.get_start_concepts(document_id, session)
    return StartConceptsAPIResponse(
        document_id=result["document_id"],
        concepts=[StartConceptItemResponse(**vars(item)) for item in result["concepts"]],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_rubric(raw: str) -> dict | None:
    """Strip markdown fences and parse rubric JSON from LLM response. Returns None on failure."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse rubric JSON: %r", raw[:200])
        return None
    if not isinstance(parsed, dict):
        return None
    if not {"accuracy", "completeness", "clarity"}.issubset(parsed.keys()):
        logger.warning("Rubric JSON missing required keys: %s", set(parsed.keys()))
        return None
    return parsed


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


async def _get_due_for_session(document_id: str, session: AsyncSession) -> list[FlashcardModel]:
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
