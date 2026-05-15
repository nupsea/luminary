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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
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
from app.repos.study_repo import StudyRepo, get_study_repo
from app.routers.flashcards import FlashcardResponse, _to_response
from app.schemas.study import (
    CardStabilityItem,
    CollectionSource,
    CollectionSubEnclave,
    CollectionTopic,
    DailyHistoryItem,
    DueCountResponse,
    GapResult,
    RubricCompletenessResponse,
    RubricDimensionResponse,
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
    StartConceptItemResponse,
    StartConceptsAPIResponse,
    StartSessionRequest,
    StrugglingCardItem,
    StudyCollectionDashboardResponse,
    StudyPathAPIResponse,
    StudyPathItemResponse,
    StudyStatsResponse,
    TeachbackRequest,
    TeachbackResponse,
    TeachbackResultItem,
    TeachbackResultsBatchResponse,
    TeachbackRubricResponse,
    TeachbackSubmitResponse,
)
from app.services.fsrs_service import get_fsrs_service
from app.services.llm import get_llm_service
from app.services.study_path_service import StudyPathService
from app.services.study_session_service import (
    build_session_plan as _build_session_plan,
)
from app.services.study_session_service import (
    compute_gaps as _compute_gaps,
)
from app.services.study_session_service import (
    compute_section_heatmap as _compute_section_heatmap,
)

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Gap-detection thresholds now live in repos/study_repo.py; no callers
# in this file or in tests still reference the old _GAP_* names.

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

# rubric evaluation prompts (duplicated in feynman_service.py -- same layer)
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




_RATING_INT_MAP: dict[int, str] = {1: "again", 2: "hard", 3: "good", 4: "easy"}


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

    # Combined collection logic -- inline queries resolve the collection hierarchy and
    # tag membership before the main count. The filter set is determined at request
    # time so the queries cannot be pre-built in a repo method.
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

    # Collection/tag filter branches -- inline for the same reason as get_due_count.
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
    repo = StudyRepo(session)
    chunk_to_section = await repo.chunk_section_id_map(
        [c.chunk_id for c in cards if c.chunk_id]
    )

    return [_to_response(c, section_id=chunk_to_section.get(c.chunk_id or "")) for c in cards]


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
    now = datetime.now(UTC)

    # (a) Count all due flashcards (no document filter). Inline because
    # this is a single-purpose count -- no shared shape with /due-count.
    due_stmt = select(func.count()).select_from(FlashcardModel).where(
        FlashcardModel.due_date <= now
    )
    due_count = (await session.execute(due_stmt)).scalar_one()

    # (b) Gap area titles across all documents (max 2 distinct non-null headings)
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

    # (c) Fetch recently accessed complete documents. Inline -- this select
    # shape isn't reused; no value in a repo method for one caller.
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
    tb_complete = [tb for tb in tb_rows if tb.status == "complete"]
    tb_pending_count = sum(1 for tb in tb_rows if tb.status == "pending")

    if tb_rows:
        scores = [tb.score for tb in tb_complete if tb.score is not None]
        cards_reviewed = len(tb_rows)
        cards_correct = sum(1 for s in scores if s >= 60)
        if tb_pending_count > 0:
            # Provisional: accuracy is unknown until evaluations finish.
            accuracy_pct: float | None = None
        else:
            accuracy_pct = round(sum(scores) / len(scores), 1) if scores else 0.0
    else:
        cards_reviewed = len(events)
        cards_correct = sum(1 for e in events if e.is_correct)
        accuracy_pct = round(cards_correct / cards_reviewed * 100, 1) if cards_reviewed > 0 else 0.0

    ended_at = datetime.now(UTC)
    sess.ended_at = ended_at
    sess.cards_reviewed = cards_reviewed
    sess.cards_correct = cards_correct
    sess.accuracy_pct = accuracy_pct
    await repo.commit_session(sess)

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
    repo: StudyRepo = Depends(get_study_repo),
) -> None:
    """Delete a study session and all associated review events and teachback results."""
    await repo.delete_session_cascade(session_id)
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
    """Return a summary of study status for all material in a collection

    Rewritten to use SQL aggregates and a small fixed number of queries regardless
    of tag count, sub-enclave count, or tree depth. Previously this endpoint could
    issue 20+ sequential queries per click.
    """
    from collections import defaultdict

    from app.routers.documents import _safe_tags

    # All queries in this endpoint share a session; the comment above the function
    # explains why the selects are inline (bespoke aggregation, flat query count).
    coll_result = await session.execute(
        select(CollectionModel.name).where(CollectionModel.id == collection_id)
    )
    coll_name = coll_result.scalar_one_or_none()
    if not coll_name:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 2. Load the collection tree once and build parent->children adjacency in Python.
    # Collections are small (typically < 200 rows) so this beats recursive CTEs for
    # clarity and keeps query count flat regardless of tree depth.
    all_colls_rows = (
        await session.execute(
            select(CollectionModel.id, CollectionModel.parent_collection_id)
        )
    ).all()
    children_of: dict[str | None, list[str]] = defaultdict(list)
    for cid, pid in all_colls_rows:
        children_of[pid].append(cid)

    def _descendants(root: str) -> set[str]:
        out = {root}
        stack = [root]
        while stack:
            cur = stack.pop()
            for child in children_of.get(cur, ()):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        return out

    hierarchy_ids = _descendants(collection_id)
    direct_children = children_of.get(collection_id, [])

    # For sub-enclave counts: compute each direct child's full descendant set and
    # track which descendants roll up to which sub-enclave root.
    descendants_by_child: dict[str, set[str]] = {
        child_id: _descendants(child_id) for child_id in direct_children
    }

    # 3. Fetch all members (docs + notes) of every collection in the hierarchy,
    # plus every direct-child subtree. One query.
    all_relevant_coll_ids = set(hierarchy_ids)
    for desc in descendants_by_child.values():
        all_relevant_coll_ids.update(desc)

    members_rows = (
        await session.execute(
            select(
                CollectionMemberModel.collection_id,
                CollectionMemberModel.member_id,
                CollectionMemberModel.member_type,
            ).where(CollectionMemberModel.collection_id.in_(list(all_relevant_coll_ids)))
        )
    ).all()

    # Bucket by hierarchy membership.
    doc_ids: set[str] = set()
    note_ids: set[str] = set()
    for coll_id, member_id, member_type in members_rows:
        if coll_id in hierarchy_ids:
            if member_type == "document":
                doc_ids.add(member_id)
            elif member_type == "note":
                note_ids.add(member_id)

    # 4. Flashcard aggregate stats -- one query, no rows pulled into memory.
    now = datetime.now(UTC)
    where_clauses = []
    if doc_ids:
        where_clauses.append(FlashcardModel.document_id.in_(list(doc_ids)))
    if note_ids:
        where_clauses.append(FlashcardModel.note_id.in_(list(note_ids)))

    if where_clauses:
        stats_row = (
            await session.execute(
                select(
                    func.count(FlashcardModel.id).label("total"),
                    func.sum(
                        case(
                            (
                                (FlashcardModel.due_date.is_not(None))
                                & (FlashcardModel.due_date <= now),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("due_today"),
                    func.sum(
                        case((FlashcardModel.fsrs_state == "new", 1), else_=0)
                    ).label("new_today"),
                    func.sum(
                        case((FlashcardModel.fsrs_stability > 30.0, 1), else_=0)
                    ).label("mastered"),
                ).where(or_(*where_clauses))
            )
        ).one()
        total = int(stats_row.total or 0)
        due_today = int(stats_row.due_today or 0)
        new_today = int(stats_row.new_today or 0)
        mastered = int(stats_row.mastered or 0)
    else:
        total = due_today = new_today = mastered = 0

    mastery_pct = round(mastered / total * 100, 1) if total else 0.0

    # 5. Topics: build tag->docs/notes maps, then a single aggregate query for card
    # counts per doc and per note. Replaces the old N+1 count loop.
    tag_to_docs: dict[str, set[str]] = defaultdict(set)
    tag_to_notes: dict[str, set[str]] = defaultdict(set)

    if doc_ids:
        docs_tag_rows = (
            await session.execute(
                select(DocumentModel.id, DocumentModel.tags).where(
                    DocumentModel.id.in_(list(doc_ids))
                )
            )
        ).all()
        for did, dtags in docs_tag_rows:
            for t in _safe_tags(dtags):
                tag_to_docs[t].add(did)

    if note_ids:
        note_tag_rows = (
            await session.execute(
                select(NoteTagIndexModel.tag_full, NoteTagIndexModel.note_id).where(
                    NoteTagIndexModel.note_id.in_(list(note_ids))
                )
            )
        ).all()
        for t, nid in note_tag_rows:
            tag_to_notes[t].add(nid)

    # Count cards per document and per note in ONE query each (two queries total).
    cards_per_doc: dict[str, int] = {}
    if doc_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.document_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.document_id.in_(list(doc_ids)))
                .group_by(FlashcardModel.document_id)
            )
        ).all()
        cards_per_doc = {did: int(cnt) for did, cnt in rows}

    cards_per_note: dict[str, int] = {}
    if note_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.note_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.note_id.in_(list(note_ids)))
                .group_by(FlashcardModel.note_id)
            )
        ).all()
        cards_per_note = {nid: int(cnt) for nid, cnt in rows}

    all_tags = set(tag_to_docs.keys()) | set(tag_to_notes.keys())
    topics: list[CollectionTopic] = []
    for t in all_tags:
        card_count = sum(cards_per_doc.get(d, 0) for d in tag_to_docs.get(t, ())) + sum(
            cards_per_note.get(n, 0) for n in tag_to_notes.get(t, ())
        )
        note_count = len(tag_to_notes.get(t, ()))
        if card_count > 0 or note_count > 0:
            topics.append(
                CollectionTopic(tag=t, card_count=card_count, note_count=note_count)
            )
    topics.sort(key=lambda x: (x.card_count, x.note_count), reverse=True)
    topics = topics[:10]

    # 6. Sources list. SUBSTR on note.content avoids streaming large note bodies
    # over the wire only to slice the first line.
    sources: list[CollectionSource] = []
    if doc_ids:
        doc_title_rows = (
            await session.execute(
                select(DocumentModel.id, DocumentModel.title).where(
                    DocumentModel.id.in_(list(doc_ids))
                )
            )
        ).all()
        for did, dtitle in doc_title_rows:
            sources.append(CollectionSource(id=did, title=dtitle, type="document"))
    if note_ids:
        note_snippet_rows = (
            await session.execute(
                select(
                    NoteModel.id,
                    func.substr(NoteModel.content, 1, 120).label("snippet"),
                ).where(NoteModel.id.in_(list(note_ids)))
            )
        ).all()
        for nid, snippet in note_snippet_rows:
            ntitle = (snippet or "").split("\n")[0][:60] or "Untitled Note"
            sources.append(CollectionSource(id=nid, title=ntitle, type="note"))

    # 7. Sub-enclaves: for each direct child we already know its full descendant set.
    # Map descendant collection ID -> sub-enclave root, then bucket the members rows
    # we already fetched. One pass, zero extra queries.
    desc_to_root: dict[str, str] = {}
    for child_id, desc_set in descendants_by_child.items():
        for d in desc_set:
            desc_to_root.setdefault(d, child_id)

    sub_doc_ids: dict[str, set[str]] = defaultdict(set)
    sub_note_ids: dict[str, set[str]] = defaultdict(set)
    for coll_id, member_id, member_type in members_rows:
        root = desc_to_root.get(coll_id)
        if root is None:
            continue
        if member_type == "document":
            sub_doc_ids[root].add(member_id)
        elif member_type == "note":
            sub_note_ids[root].add(member_id)

    # Child card counts reuse cards_per_doc / cards_per_note -- but those only cover
    # hierarchy_ids members. Sub-enclave members can include docs/notes outside the
    # parent hierarchy (when a child enclave directly holds an item the parent does
    # not). Top up with one extra pair of queries for any missing IDs.
    missing_doc_ids = (
        set().union(*sub_doc_ids.values()) if sub_doc_ids else set()
    ) - doc_ids
    missing_note_ids = (
        set().union(*sub_note_ids.values()) if sub_note_ids else set()
    ) - note_ids
    if missing_doc_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.document_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.document_id.in_(list(missing_doc_ids)))
                .group_by(FlashcardModel.document_id)
            )
        ).all()
        for did, cnt in rows:
            cards_per_doc[did] = int(cnt)
    if missing_note_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.note_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.note_id.in_(list(missing_note_ids)))
                .group_by(FlashcardModel.note_id)
            )
        ).all()
        for nid, cnt in rows:
            cards_per_note[nid] = int(cnt)

    child_name_map: dict[str, str] = {}
    if direct_children:
        name_rows = (
            await session.execute(
                select(CollectionModel.id, CollectionModel.name).where(
                    CollectionModel.id.in_(direct_children)
                )
            )
        ).all()
        child_name_map = {cid: name for cid, name in name_rows}

    sub_collections: list[CollectionSubEnclave] = []
    for child_id in direct_children:
        count = sum(cards_per_doc.get(d, 0) for d in sub_doc_ids.get(child_id, ())) + sum(
            cards_per_note.get(n, 0) for n in sub_note_ids.get(child_id, ())
        )
        sub_collections.append(
            CollectionSubEnclave(
                id=child_id,
                name=child_name_map.get(child_id, ""),
                card_count=count,
            )
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

    # Map session_id -> pending teach-back count so the UI knows which rows
    # still need polling. Single grouped query beats N+1.
    session_ids = [s.id for s in sessions]
    pending_by_session: dict[str, int] = {}
    if session_ids:
        pending_result = await db.execute(
            select(
                TeachbackResultModel.session_id,
                func.count().label("n"),
            )
            .where(
                TeachbackResultModel.session_id.in_(session_ids),
                TeachbackResultModel.status == "pending",
            )
            .group_by(TeachbackResultModel.session_id)
        )
        pending_by_session = {
            sid: n for sid, n in pending_result.all() if sid is not None
        }

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
    """
    sess_result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    sess = sess_result.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    planned_ids: list[str] = list(sess.planned_card_ids or [])
    if not planned_ids:
        logger.warning(
            "remaining-cards: session has empty planned_card_ids",
            extra={"session_id": session_id, "ended_at": str(sess.ended_at)},
        )
        return SessionRemainingResponse(
            answered_count=0, planned_count=0, cards=[]
        )

    # A card is "answered" if it has a teach-back result OR a review event for this session.
    tb_result = await db.execute(
        select(TeachbackResultModel.flashcard_id).where(
            TeachbackResultModel.session_id == session_id
        )
    )
    answered: set[str] = {row[0] for row in tb_result.all()}
    rev_result = await db.execute(
        select(ReviewEventModel.flashcard_id).where(
            ReviewEventModel.session_id == session_id
        )
    )
    answered.update(row[0] for row in rev_result.all())

    # Restrict answered to planned members so the count reflects the planned queue.
    planned_set = set(planned_ids)
    answered_in_planned = answered & planned_set
    remaining_ids = [cid for cid in planned_ids if cid not in answered_in_planned]
    if not remaining_ids:
        return SessionRemainingResponse(
            answered_count=len(answered_in_planned),
            planned_count=len(planned_ids),
            cards=[],
        )

    cards_result = await db.execute(
        select(FlashcardModel).where(FlashcardModel.id.in_(remaining_ids))
    )
    cards_by_id = {c.id: c for c in cards_result.scalars().all()}
    # Preserve the original planned order.
    ordered = [_to_response(cards_by_id[cid]) for cid in remaining_ids if cid in cards_by_id]
    return SessionRemainingResponse(
        answered_count=len(answered_in_planned),
        planned_count=len(planned_ids),
        cards=ordered,
    )


@router.post("/teachback", response_model=TeachbackResponse)
async def teachback(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResponse:
    """Evaluate a student's teach-back explanation with LLM. Tracks misconceptions."""
    # Flashcard lookup; shares session with the persist writes below so all
    # teachback artifacts (result row, misconceptions, correction card) commit together.
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

    # rubric evaluation (second LLM call; graceful fallback on failure)
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

    # Persist all teachback artifacts (result + optional misconceptions) atomically;
    # the correction card is generated mid-session so it must land in the same tx.
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


async def _finalize_session_tally_if_ready(
    session: AsyncSession,
    session_id: str,
) -> None:
    """Recompute session tally once the last pending teach-back completes.

    Called from the background evaluator after writing a teach-back result.
    No-op if the session hasn't been ended yet, or if there are still pending
    evaluations (they will trigger the final update themselves).
    """
    sess_result = await session.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    sess = sess_result.scalar_one_or_none()
    if sess is None or sess.ended_at is None:
        return

    tb_result = await session.execute(
        select(TeachbackResultModel).where(
            TeachbackResultModel.session_id == session_id,
        )
    )
    tb_rows = tb_result.scalars().all()
    if not tb_rows:
        return
    if any(tb.status == "pending" for tb in tb_rows):
        return

    complete = [tb for tb in tb_rows if tb.status == "complete"]
    scores = [tb.score for tb in complete if tb.score is not None]
    sess.cards_reviewed = len(tb_rows)
    sess.cards_correct = sum(1 for s in scores if s >= 60)
    sess.accuracy_pct = round(sum(scores) / len(scores), 1) if scores else 0.0
    logger.info(
        "Study session tally finalized",
        extra={
            "session_id": session_id,
            "cards_reviewed": sess.cards_reviewed,
            "cards_correct": sess.cards_correct,
            "accuracy_pct": sess.accuracy_pct,
        },
    )


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

    rating = _score_to_rating(score)

    # LLM call 3: correction flashcard (if any) -- generated BEFORE the write
    # transaction. Holding the SQLite write lock while an LLM call is in flight
    # starves concurrent HTTP inserts past busy_timeout.
    correction_payload: dict | None = None
    correction_card: FlashcardModel | None = None
    if score < 60 and misconceptions:
        session_factory = get_session_factory()
        # Separate read session so the card fetch does not hold a write lock
        # during the LLM correction card generation that follows.
        async with session_factory() as read_session:
            card_result = await read_session.execute(
                select(FlashcardModel).where(FlashcardModel.id == card_id)
            )
            correction_card = card_result.scalar_one_or_none()
        if correction_card:
            correction_payload = await _llm_correction_card_payload(
                card=correction_card,
                misconception=misconceptions[0],
            )

    # Serialize DB writes to avoid SQLite "database is locked" (invariant I-1)
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

                # Misconceptions + correction flashcard (LLM already resolved above)
                if score < 60 and misconceptions and correction_card:
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
                    if correction_payload is not None:
                        _insert_correction_flashcard(
                            card=correction_card,
                            payload=correction_payload,
                            session=session,
                        )

                # Self-heal session tally: if the parent session has already
                # been ended by the user (e.g. they navigated away mid-eval)
                # and this was the last pending evaluation, recompute
                # cards_correct / accuracy_pct on the session row so session
                # history reflects the final scores.
                if session_id:
                    await _finalize_session_tally_if_ready(session, session_id)

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
    # Existence check + pending row persist share one session; the bg evaluator
    # opens its own session (invariant I-1).
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

    # Cross-table join (TeachbackResultModel + FlashcardModel) for question/answer text;
    # no repo owns both tables, so the join lives in the router.
    stmt = (
        select(TeachbackResultModel, FlashcardModel.question, FlashcardModel.answer)
        .join(
            FlashcardModel,
            TeachbackResultModel.flashcard_id == FlashcardModel.id,
            isouter=True,
        )
        .where(TeachbackResultModel.id.in_(id_list))
    )
    rows = (await session.execute(stmt)).all()

    items: list[TeachbackResultItem] = []
    for tb, question, expected_answer in rows:
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
                expected_answer=expected_answer or "",
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
    # Cross-table join for question/answer text; same pattern as get_teachback_results.
    stmt = (
        select(TeachbackResultModel, FlashcardModel.question, FlashcardModel.answer)
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
    for tb, question, expected_answer in rows:
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
                expected_answer=expected_answer or "",
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
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = select(StudySessionModel).where(
        StudySessionModel.started_at >= cutoff,
        StudySessionModel.ended_at.is_not(None),
    )
    if document_id:
        stmt = stmt.where(StudySessionModel.document_id == document_id)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

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


@router.get("/section-heatmap", response_model=SectionHeatmapResponse)
async def get_section_heatmap(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SectionHeatmapResponse:
    """Return per-section FSRS fragility scores for a document.

    fragility_score ranges from 0.0 (well-retained) to 1.0 (completely forgotten).
    Sections with no flashcards are absent from the heatmap dict.
    """
    # Two sequential reads: cards first (to get chunk_ids), then chunk→section mapping.
    # The chunk_ids set is only known after the card query, so the second read follows here.
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
# Study path endpoints
# ---------------------------------------------------------------------------




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


async def _llm_correction_card_payload(
    card: FlashcardModel,
    misconception: str,
) -> dict | None:
    """Run the LLM call for a correction flashcard -- no DB I/O.

    Split out from _generate_correction_flashcard so the LLM round-trip can
    happen OUTSIDE the SQLite write transaction. Holding the write lock during
    an LLM call starves concurrent HTTP inserts past the busy_timeout.
    """
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
    return data


def _insert_correction_flashcard(
    card: FlashcardModel,
    payload: dict,
    session: AsyncSession,
) -> str:
    """Insert a correction flashcard row -- caller must have the LLM payload."""
    new_id = str(uuid.uuid4())
    correction = FlashcardModel(
        id=new_id,
        document_id=card.document_id,
        chunk_id=card.chunk_id,
        question=payload.get("question", f"Correction: {card.question}"),
        answer=payload.get("answer", card.answer),
        source_excerpt=payload.get("source_excerpt", ""),
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=datetime.now(UTC),
        reps=0,
        lapses=0,
    )
    session.add(correction)  # correction card persisted in caller's session; commit is caller's responsibility
    return new_id


async def _generate_correction_flashcard(
    card: FlashcardModel,
    misconception: str,
    session: AsyncSession,
) -> str | None:
    """LLM-generate and persist a correction flashcard.

    Kept for the sync /teachback endpoint which already runs outside the
    background semaphore path. New code should call the split helpers so the
    LLM call happens outside the DB transaction.
    """
    payload = await _llm_correction_card_payload(card, misconception)
    if payload is None:
        return None
    return _insert_correction_flashcard(card, payload, session)


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
