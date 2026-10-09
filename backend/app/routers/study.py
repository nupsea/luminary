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

import logging
import math
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import (
    FlashcardModel,
    ReviewEventModel,
    StudyEventModel,
)
from app.repos.collection_repo import CollectionRepo
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.study_repo import DueScope, StudyRepo, get_study_repo
from app.routers.flashcards import FlashcardResponse, _to_response
from app.schemas.study import (
    AppendSessionCardsRequest,
    AppendSessionCardsResponse,
    AssemblePreview,
    AssembleRequest,
    AssembleResponse,
    CalibrationStatsResponse,
    CalibrationWeekItem,
    CardStabilityItem,
    DailyHistoryItem,
    DecayDebtItem,
    DecayDebtResponse,
    DocumentTopicsResponse,
    DueCountResponse,
    GapResult,
    MisconceptionStatsResponse,
    SectionHeatmapItem,
    SectionHeatmapResponse,
    SectionStabilityItem,
    SessionCardDetail,
    SessionCardResponse,
    SessionListItem,
    SessionListResponse,
    SessionPlanItem,
    SessionPlanResponse,
    SessionRemainingResponse,
    SessionResponse,
    SessionReviewRequest,
    SessionReviewResponse,
    SessionStartResponse,
    SessionSummary,
    StartSessionRequest,
    StrugglingCardItem,
    StudyCollectionDashboardResponse,
    StudyStatsResponse,
    TeachbackRequest,
    TeachbackResponse,
    TeachbackResultsBatchResponse,
    TeachbackSubmitResponse,
    TopicItem,
)
from app.services import study_assembler, teachback_service
from app.services.collection_dashboard import collection_dashboard
from app.services.fsrs_service import get_fsrs_service
from app.services.mastery_service import get_mastery_service
from app.services.misconceptions import (
    get_stats as get_misconception_stats,
)
from app.services.study_queue import due_scope
from app.services.study_session_service import (
    build_session_plan as _build_session_plan,
)
from app.services.study_session_service import (
    compute_gaps as _compute_gaps,
)
from app.services.study_session_service import (
    compute_section_heatmap as _compute_section_heatmap,
)
from app.services.teachback_service import latest_event_per_card, teachback_tally
from app.services.topic_service import get_topic_service

logger = logging.getLogger(__name__)

# Back-compat re-exports for tests and feynman.py that import these here.
__all__ = [
    "SectionHeatmapItem",
    "SessionPlanItem",
    "_build_session_plan",
    "_compute_gaps",
    "_compute_section_heatmap",
    "router",
]

router = APIRouter(prefix="/study", tags=["study"])

# Gap-detection thresholds live in repos/study_repo.py.


_RATING_INT_MAP: dict[int, str] = {1: "again", 2: "hard", 3: "good", 4: "easy"}


@router.get("/due-count", response_model=DueCountResponse)
async def get_due_count(
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    document_ids: list[str] | None = Query(default=None),
    note_ids: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> DueCountResponse:
    """Return the count of flashcards whose due_date is today or in the past."""
    scope = await due_scope(
        session,
        document_ids=document_ids,
        note_ids=note_ids,
        collection_id=collection_id,
        tag=tag,
    )
    count = await StudyRepo(session).count_due(scope)
    logger.debug("due-count: %d cards due", count)
    return DueCountResponse(due_today=count)


@router.get("/due", response_model=list[FlashcardResponse])
async def get_due_cards(
    document_id: str | None = None,
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    document_ids: list[str] | None = Query(default=None),
    note_ids: list[str] | None = Query(default=None),
    section_id: str | None = Query(default=None),
    limit: int = 20,
    session: AsyncSession = Depends(get_db),
) -> list[FlashcardResponse]:
    """Return flashcards whose due_date is now or in the past."""
    scope = await due_scope(
        session,
        document_ids=document_ids or ([document_id] if document_id else []),
        note_ids=note_ids,
        collection_id=collection_id,
        tag=tag,
        section_id=section_id,
    )
    repo = StudyRepo(session)
    cards = await repo.list_due(scope, limit=limit)

    # Build chunk_id -> section_id map for SourcePanel
    chunk_to_section = await repo.chunk_section_id_map([c.chunk_id for c in cards if c.chunk_id])

    return [_to_response(c, section_id=chunk_to_section.get(c.chunk_id or "")) for c in cards]


@router.post("/assemble", response_model=AssembleResponse, status_code=201)
async def assemble_study(
    req: AssembleRequest,
    session: AsyncSession = Depends(get_db),
) -> AssembleResponse:
    """Study Launcher backend: resolve a scope -> a valid Study Event (docs/study-launcher.md).

    Returns the assembled due-card set + an honest preview, and records a StudyEvent row.
    Mode-aware: teachback_available reflects the feynman surface (full mode only). Model-down still
    yields due cards (generation is a separate seam).
    """
    result = await study_assembler.assemble(
        session,
        req.scope_type,
        req.scope_ref,
        length_min=req.length_min,
        want_generated=req.want_generated,
        # actually generate only on Start (commit), not on live preview
        do_generate=req.commit and req.want_generated,
    )

    event_id = ""
    if req.commit:
        event_id = uuid.uuid4().hex
        session.add(
            StudyEventModel(
                id=event_id,
                kind=req.mode,
                scope_type=req.scope_type,
                scope_ref=req.scope_ref,
            )
        )
        await session.commit()

    repo = StudyRepo(session)
    chunk_to_section = await repo.chunk_section_id_map(
        [c.chunk_id for c in result.cards if c.chunk_id]
    )
    cards = [
        _to_response(c, section_id=chunk_to_section.get(c.chunk_id or "")) for c in result.cards
    ]
    teachback_available = get_settings().LUMINARY_MODE == "full"

    return AssembleResponse(
        event_id=event_id,
        scope_type=req.scope_type,
        scope_ref=req.scope_ref,
        mode=req.mode,
        concept_ids=result.concept_ids,
        cards=cards,
        preview=AssemblePreview(
            due_count=result.preview.due_count,
            generated_count=result.preview.generated_count,
            mapped_count=result.preview.mapped_count,
            unmapped_count=result.preview.unmapped_count,
            topic_mix=result.preview.topic_mix,
            thin_scope_warning=result.preview.thin_scope_warning,
        ),
        teachback_available=teachback_available,
    )


@router.get("/session-plan", response_model=SessionPlanResponse)
async def get_session_plan(
    minutes: int = Query(default=20, ge=5, le=120),
    session: AsyncSession = Depends(get_db),
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionPlanResponse:
    """Return a prioritized study agenda for the given time budget.

    DB-only -- no LLM. Due count, gap areas, and recent docs assembled
    and passed to the pure _build_session_plan() function.
    """
    due_count = await repo.count_due(DueScope())

    # Gap area titles across all documents (max 2 distinct non-null headings)
    weak_cards = list(await repo.list_weak_flashcards())
    gap_area_titles: list[str] = []
    if weak_cards:
        chunk_to_section = await repo.chunk_section_headings(
            [c.chunk_id for c in weak_cards if c.chunk_id]
        )
        seen: set[str] = set()
        for heading in chunk_to_section.values():
            if heading and heading not in seen and len(gap_area_titles) < 2:
                seen.add(heading)
                gap_area_titles.append(heading)

    docs = await DocumentRepo(session).list_recently_accessed_complete(limit=3)
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
    repo: StudyRepo = Depends(get_study_repo),
) -> list[GapResult]:
    """Return sections with weak (seen but fragile) flashcards, ordered by avg stability."""
    weak_cards = list(await repo.list_weak_flashcards(document_id=document_id))
    if not weak_cards:
        return []
    chunk_to_section = await repo.chunk_section_headings(
        [c.chunk_id for c in weak_cards if c.chunk_id]
    )
    return _compute_gaps(weak_cards, chunk_to_section)


@router.get("/sessions/open", response_model=SessionResponse)
async def get_open_session(
    mode: str,
    document_id: str | None = None,
    collection_id: str | None = None,
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionResponse:
    """Return the most recent still-open session matching this scope.

    Used by the hook to auto-resume an in-progress session instead of creating
    a duplicate when the user clicks Start. Scope match is exact: a null
    document_id only matches sessions with null document_id.
    """
    sess = await repo.find_open_session(
        mode=mode,
        document_id=document_id,
        collection_id=collection_id,
    )
    if sess is None:
        raise HTTPException(status_code=404, detail="No open session")
    return SessionResponse.model_validate(sess)


@router.post("/sessions/start", response_model=SessionResponse, status_code=201)
async def start_session(
    req: StartSessionRequest,
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionResponse:
    """Create a new study session row and return its ID."""
    sess = await repo.create_session(
        document_id=req.document_id,
        collection_id=req.collection_id,
        mode=req.mode,
        planned_card_ids=req.planned_card_ids,
    )
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


async def _write_back_concept_mastery(
    session: AsyncSession, events: list[ReviewEventModel]
) -> None:
    """Recompute + store mastery for the concepts whose cards were reviewed this session."""
    card_ids = list({e.flashcard_id for e in events})
    concept_ids = await FlashcardRepo(session).concept_ids_for_cards(card_ids)
    if not concept_ids:
        return
    await get_mastery_service().recompute_for_concepts(session, concept_ids)
    await session.commit()


@router.post("/sessions/{session_id}/end", response_model=SessionSummary)
async def end_session(
    session_id: str,
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionSummary:
    """Close a study session, tally review events, and return the summary."""
    sess = await repo.get_session_or_404(session_id)
    events = await repo.list_review_events(session_id)

    # Pull all teach-back rows (pending + complete). Pending rows mean the
    # background evaluator has not yet scored the answer -- we still count them
    # toward cards_reviewed (the user did answer) but leave accuracy provisional
    # until the last evaluation lands. _evaluate_teachback_bg finalizes the
    # tally when the last pending row flips to "complete".
    tb_rows = await repo.list_teachback_results(session_id)
    tb_pending_count = 0

    if tb_rows:
        # Latest attempt per card, not per submission: see _latest_attempt_per_card.
        cards_reviewed, cards_correct, accuracy_pct, tb_pending_count = teachback_tally(tb_rows)
    else:
        # Latest event per card, for the same reason the teach-back arm reads its
        # latest attempt: a card graded twice in one sitting is one card
        # reviewed. `len(events)` counted the grades, which is the defect that
        # reached a learner as "30 of 15 reviewed" on the other arm (I-46).
        latest = latest_event_per_card(events)
        cards_reviewed = len(latest)
        cards_correct = sum(1 for e in latest if e.is_correct)
        accuracy_pct: float | None = (
            round(cards_correct / cards_reviewed * 100, 1) if cards_reviewed > 0 else 0.0
        )

    ended_at = datetime.now(UTC)
    sess.ended_at = ended_at
    sess.cards_reviewed = cards_reviewed
    sess.cards_correct = cards_correct
    sess.accuracy_pct = accuracy_pct
    await repo.commit_session(sess)

    # Write-back: the assessment pipeline writes the grounded mastery to the concepts
    # touched this session (I-19). Best-effort -- a concepts hiccup never fails the end.
    try:
        await _write_back_concept_mastery(repo.session, events)
    except Exception:
        logger.warning("end_session: concept mastery write-back failed", exc_info=True)

    logger.info(
        "Study session ended",
        extra={
            "session_id": session_id,
            "cards_reviewed": cards_reviewed,
            "cards_correct": cards_correct,
            "accuracy_pct": accuracy_pct,
            "pending_evaluations": tb_pending_count,
        },
    )
    return SessionSummary(
        session_id=sess.id,
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        accuracy_pct=accuracy_pct if accuracy_pct is not None else 0.0,
        ended_at=ended_at,
    )


@router.post("/sessions/{session_id}/reopen", status_code=204)
async def reopen_session(
    session_id: str,
    repo: StudyRepo = Depends(get_study_repo),
) -> None:
    """Clear ended_at on a session so the user can Continue adding answers.

    Tallies are reset; _finalize_session_tally_if_ready recomputes them the
    next time the session is ended and all evaluations are complete.
    """
    sess = await repo.get_session_or_404(session_id)
    sess.ended_at = None
    sess.cards_correct = 0
    sess.accuracy_pct = None
    await repo.commit_session(sess)
    logger.info("Study session reopened", extra={"session_id": session_id})


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    if_unused: bool = False,
    repo: StudyRepo = Depends(get_study_repo),
) -> None:
    """Delete a study session and all associated review events and teachback results.

    ``if_unused`` deletes only a session with no attempt in it, and is a no-op otherwise.
    """
    if if_unused:
        if await repo.discard_session_if_unused(session_id):
            logger.info("Unused study session discarded", extra={"session_id": session_id})
        return
    await repo.delete_session_cascade(session_id)
    logger.info("Study session deleted", extra={"session_id": session_id})


@router.get(
    "/collections/{collection_id}/dashboard", response_model=StudyCollectionDashboardResponse
)
async def get_collection_study_dashboard(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> StudyCollectionDashboardResponse:
    """Study status for everything in a collection and the collections below it."""
    return await collection_dashboard(session, collection_id)


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
    repo = StudyRepo(db)
    total, sessions = await repo.list_sessions(
        document_id=document_id,
        collection_id=collection_id,
        mode=mode,
        status=status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    doc_titles = await DocumentRepo(db).titles(
        list({s.document_id for s in sessions if s.document_id})
    )
    coll_names = await CollectionRepo(db).names(
        list({s.collection_id for s in sessions if s.collection_id})
    )
    # The UI polls only the rows that still have a teach-back being graded.
    pending_by_session = await repo.pending_teachback_counts([s.id for s in sessions])

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
                has_pending_evaluations=pending_by_session.get(sess.id, 0) > 0,
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
    repo = StudyRepo(db)
    await repo.get_session_or_404(session_id)
    rows = await repo.list_review_events_with_cards(session_id)

    return [
        SessionCardDetail(
            flashcard_id=event.flashcard_id,
            question=card.question,
            answer=card.answer or "",
            source_excerpt=card.source_excerpt,
            section_heading=card.section_heading,
            chunk_id=card.chunk_id,
            rating=event.rating,
            is_correct=event.is_correct,
            predicted_rating=getattr(event, "predicted_rating", None),
            reviewed_at=event.reviewed_at,
        )
        for event, card in rows
    ]


@router.post(
    "/sessions/{session_id}/cards",
    response_model=AppendSessionCardsResponse,
)
async def append_session_cards(
    session_id: str,
    req: AppendSessionCardsRequest,
    repo: StudyRepo = Depends(get_study_repo),
) -> AppendSessionCardsResponse:
    """Add cards to an open session's planned queue.

    A run is reconstructed from `planned_card_ids` on every resume, so cards
    generated mid-run have to join the queue here and not only in the client's
    memory -- otherwise the reader adds five questions, answers two, closes the
    tab, and comes back to a run that never heard of them.

    Ids that are not real cards are dropped rather than queued: a planned id
    with no row behind it makes `remaining-cards` return a shorter queue than
    `planned_count` promises, which reads as a run stuck short of its own total.
    """
    sess = await repo.get_session_or_404(session_id)
    live_ids = set(await FlashcardRepo(repo.session).list_existing_ids_in(req.card_ids))
    added = repo.append_planned_cards(sess, [cid for cid in req.card_ids if cid in live_ids])
    if added:
        await repo.commit_session(sess)
    planned_count = len(sess.planned_card_ids or [])
    logger.info(
        "Study session cards appended",
        extra={
            "session_id": session_id,
            "requested": len(req.card_ids),
            "added": added,
            "planned_count": planned_count,
        },
    )
    return AppendSessionCardsResponse(
        session_id=session_id, added=added, planned_count=planned_count
    )


@router.get(
    "/sessions/{session_id}/remaining-cards",
    response_model=SessionRemainingResponse,
)
async def get_session_remaining_cards(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> SessionRemainingResponse:
    """Return the unanswered flashcards from this session's planned queue.

    Used by resume so the queue reflects what was originally planned, not the
    set of cards currently due for the scope. Also returns the count of already-
    answered cards so the hook can restore the progress indicator on resume.

    Both counts are over the planned cards that STILL EXIST: a deck replaced
    under an open run deletes cards it planned, and those are neither progress
    nor work outstanding (I-47).
    """
    repo = StudyRepo(db)
    sess = await repo.get_session_or_404(session_id)

    planned_ids: list[str] = list(sess.planned_card_ids or [])
    if not planned_ids:
        logger.warning(
            "remaining-cards: session has empty planned_card_ids",
            extra={"session_id": session_id, "ended_at": str(sess.ended_at)},
        )
        return SessionRemainingResponse(answered_count=0, planned_count=0, cards=[])

    answered = await repo.answered_card_ids(session_id)

    # Planned means planned AND still there. Replacing a deck deletes the cards
    # an open run planned, and counting the dead ids made the header read "7 of 8
    # reviewed" over a deck of three: five of the seven were cards no learner
    # could be shown again. A deleted card leaves BOTH sides of the ratio -- it is
    # not progress, and it is not work outstanding either. The client cannot
    # repair this downstream, because dropping the dead ids from `cards` alone
    # keeps answered + remaining == planned and the inflation stays invisible.
    live_by_id = await FlashcardRepo(db).get_many(planned_ids)
    # Preserve the original planned order.
    live_planned = [cid for cid in planned_ids if cid in live_by_id]

    answered_in_planned = answered & set(live_planned)
    remaining_ids = [cid for cid in live_planned if cid not in answered_in_planned]
    return SessionRemainingResponse(
        answered_count=len(answered_in_planned),
        planned_count=len(live_planned),
        cards=[_to_response(live_by_id[cid]) for cid in remaining_ids],
    )


@router.post("/teachback", response_model=TeachbackResponse)
async def teachback(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResponse:
    """Evaluate a student's teach-back explanation with LLM. Tracks misconceptions."""
    return await teachback_service.evaluate_now(session, req.flashcard_id, req.user_explanation)


@router.post("/teachback/async", response_model=TeachbackSubmitResponse)
async def teachback_async(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackSubmitResponse:
    """Submit teach-back for background evaluation. Returns immediately."""
    tb_id = await teachback_service.submit(
        session, req.flashcard_id, req.user_explanation, req.session_id
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
    return await teachback_service.results(session, ids=id_list)


@router.get(
    "/sessions/{session_id}/teachback-results",
    response_model=TeachbackResultsBatchResponse,
)
async def get_session_teachback_results(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResultsBatchResponse:
    """Get all teach-back results for a study session."""
    return await teachback_service.results(session, session_id=session_id)


@router.get("/stats/{document_id}", response_model=StudyStatsResponse)
async def get_study_stats(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> StudyStatsResponse:
    """Return progress statistics for a document."""
    now = datetime.now(UTC)

    repo = StudyRepo(db)
    all_cards = await FlashcardRepo(db).list_for_document(document_id, newest_first=False)
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

    sessions = await repo.list_sessions_for_document(document_id)

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
    per_section: list[SectionStabilityItem] = []
    if all_cards:
        chunk_to_heading = await repo.chunk_section_headings(
            [c.chunk_id for c in all_cards if c.chunk_id]
        )
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
    tz_offset_minutes: int = Query(
        default=0,
        description=(
            "Client's timezone offset from UTC in minutes, matching JS "
            "`Date.getTimezoneOffset()` (positive west of UTC; PDT=420). "
            "Sessions are bucketed by the user's local date so a study "
            "session at 11pm local doesn't appear on the next day."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> list[DailyHistoryItem]:
    """Return daily study activity for the last N days, bucketed in local time."""
    sessions = await StudyRepo(db).list_ended_sessions_since(
        datetime.now(UTC) - timedelta(days=days), document_id=document_id
    )

    # Group by local date: shift UTC -> client-local before taking .date()
    local_shift = timedelta(minutes=-tz_offset_minutes)
    daily: dict[date, dict] = {}
    for s in sessions:
        if not s.ended_at:
            continue
        d = (s.started_at + local_shift).date()
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


_DECAY_DEBT_RETENTION_THRESHOLD = 0.80
_DECAY_DEBT_WINDOW_DAYS = 7
_DECAY_DEBT_LIMIT = 10


@router.get("/decay-debt", response_model=DecayDebtResponse)
async def get_decay_debt(
    limit: int = Query(default=_DECAY_DEBT_LIMIT, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> DecayDebtResponse:
    """Return documents whose flashcards are approaching the forgetting threshold.

    A card is 'at risk' when its estimated current retention R = e^(-t/S)
    drops below _DECAY_DEBT_RETENTION_THRESHOLD within the next
    _DECAY_DEBT_WINDOW_DAYS days. Results are grouped by document and sorted
    by avg_retention ascending (weakest first).
    """
    now = datetime.now(UTC)
    cards = await FlashcardRepo(session).scheduled_document_cards()
    if not cards:
        return DecayDebtResponse(items=[], total_at_risk=0)
    doc_title_map = await DocumentRepo(session).titles(list({c[0] for c in cards}))

    doc_cards: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for doc_id, stability, due_date in cards:
        # days elapsed since the scheduled due date (positive = overdue)
        due_aware = due_date.replace(tzinfo=UTC) if due_date.tzinfo is None else due_date
        days_since_due = (now - due_aware).total_seconds() / 86400
        # stability is measured in days; retention at 'days_since_due' days past due
        current_retention = math.exp(-max(0.0, days_since_due) / stability)
        # R_target = e^(-t/S)  =>  t = -S * ln(R_target)
        days_to_threshold = -stability * math.log(_DECAY_DEBT_RETENTION_THRESHOLD) - max(
            0.0, days_since_due
        )
        at_risk = (
            current_retention < _DECAY_DEBT_RETENTION_THRESHOLD
            or days_to_threshold <= _DECAY_DEBT_WINDOW_DAYS
        )
        if at_risk:
            doc_cards[doc_id].append((current_retention, int(max(0, days_to_threshold))))

    if not doc_cards:
        return DecayDebtResponse(items=[], total_at_risk=0)

    items: list[DecayDebtItem] = []
    for doc_id, at_risk in doc_cards.items():
        avg_ret = sum(r for r, _ in at_risk) / len(at_risk)
        min_days = min(d for _, d in at_risk)
        items.append(
            DecayDebtItem(
                document_id=doc_id,
                document_title=doc_title_map.get(doc_id, "(unknown)"),
                card_count=len(at_risk),
                avg_retention=round(avg_ret, 3),
                due_within_days=min_days,
            )
        )

    items.sort(key=lambda x: x.avg_retention)
    total_at_risk = sum(i.card_count for i in items)
    return DecayDebtResponse(items=items[:limit], total_at_risk=total_at_risk)


@router.get("/misconception-stats", response_model=MisconceptionStatsResponse)
async def misconception_stats(
    session: AsyncSession = Depends(get_db),
) -> MisconceptionStatsResponse:
    return MisconceptionStatsResponse(**await get_misconception_stats(session))


@router.get("/calibration-stats", response_model=CalibrationStatsResponse)
async def get_calibration_stats(
    days: int = Query(default=30, ge=7, le=90),
    session: AsyncSession = Depends(get_db),
) -> CalibrationStatsResponse:
    rows = await StudyRepo(session).predictions_since(datetime.now(UTC) - timedelta(days=days))
    if not rows:
        return CalibrationStatsResponse(overall_match_rate=None, total_predictions=0, weeks=[])

    week_buckets: dict[str, list[bool]] = defaultdict(list)
    for predicted, actual, reviewed_at in rows:
        aware = reviewed_at.replace(tzinfo=UTC) if reviewed_at.tzinfo is None else reviewed_at
        monday = (aware - timedelta(days=aware.weekday())).date().isoformat()
        week_buckets[monday].append(predicted == actual)

    weeks: list[CalibrationWeekItem] = []
    for week_start in sorted(week_buckets):
        matches = week_buckets[week_start]
        matched = sum(matches)
        weeks.append(
            CalibrationWeekItem(
                week_start=week_start,
                total=len(matches),
                matched=matched,
                match_rate=round(matched / len(matches), 3),
            )
        )

    total = len(rows)
    overall_matched = sum(1 for p, a, _ in rows if p == a)
    return CalibrationStatsResponse(
        overall_match_rate=round(overall_matched / total, 3),
        total_predictions=total,
        weeks=weeks,
    )


@router.get("/section-heatmap", response_model=SectionHeatmapResponse)
async def get_section_heatmap(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SectionHeatmapResponse:
    """Return per-section FSRS fragility scores for a document.

    fragility_score ranges from 0.0 (well-retained) to 1.0 (completely forgotten).
    Sections with no flashcards are absent from the heatmap dict.
    """
    cards = list(await FlashcardRepo(session).list_for_document(document_id, newest_first=False))
    if not cards:
        return SectionHeatmapResponse(heatmap={})
    chunk_to_section = await StudyRepo(session).chunk_section_id_map(
        [c.chunk_id for c in cards if c.chunk_id]
    )

    now = datetime.now(UTC)
    heatmap = _compute_section_heatmap(cards, chunk_to_section, now)
    logger.info(
        "section-heatmap: document_id=%s sections_with_cards=%d",
        document_id,
        len(heatmap),
    )
    return SectionHeatmapResponse(heatmap=heatmap)


# Lightweight session API (stateless start + review)


@router.post("/session/{document_id}/start", response_model=SessionStartResponse)
async def session_start(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SessionStartResponse:
    """Return the first due/new flashcard for a document and the total remaining count."""
    cards = await StudyRepo(session).due_or_unscheduled_for_document(document_id)
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

    remaining = await StudyRepo(session).due_or_unscheduled_for_document(document_id)
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


@router.get("/topics/{document_id}", response_model=DocumentTopicsResponse)
async def get_document_topics(
    document_id: str, session: AsyncSession = Depends(get_db)
) -> DocumentTopicsResponse:
    """A document's study topics from its authored structure (top-level headings, front/back-matter
    filtered out) -- or an LLM outline when heading detection is messy. Never an INDEX or publisher
    boilerplate."""
    data = await get_topic_service().document_topics(session, document_id)
    if data is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentTopicsResponse(**data)


@router.get("/sections/{document_id}", response_model=list[TopicItem])
async def get_document_sections(
    document_id: str,
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[TopicItem]:
    """All real sub-sections of a document (junk filtered, searchable) for drill-down."""
    rows = await get_topic_service().document_sections(session, document_id, q=q, limit=limit)
    return [TopicItem(**r) for r in rows]
