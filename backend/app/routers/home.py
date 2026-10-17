"""Luminary home hub overview (plan 2E.8).

GET /home/overview is the single-fetch contract for the hub UI. It composes
recent-activity, active-collections, recent-tags, and a today_action CTA so
the hub never makes a follow-up call per section.

Content tables are read-only here (the only writer of content_activity is
ActivityService); the recommender upserts its own recommendation_feedback
shown-counts as a side effect of the overview fetch.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repos.home_repo import HomeRepo
from app.schemas.home import (
    ActiveCollection,
    ContinueNoteItem,
    ContinueReadingItem,
    ContinueStudyItem,
    FadingItem,
    HomeOverviewResponse,
    RecentItem,
    RecentTag,
    TodayAction,
    WeeklyStats,
)
from app.services import recommender_service
from app.services.time_on_task_service import TimeOnTaskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/home", tags=["home"])


_RECENT_LIMIT = 10
_ACTIVE_COLLECTIONS_LIMIT = 4
_RECENT_TAGS_LIMIT = 6
_CONTINUE_READING_LIMIT = 3
_CONTINUE_NOTES_LIMIT = 3
_FADING_LIMIT = 3
# Decay window: items last touched between 7 and 21 days ago count as
# fading. Inside 7d still feels "current"; past 21d the user has likely
# moved on, surfacing it as a refresher gets noisy.
_FADING_MIN_DAYS = 7
_FADING_MAX_DAYS = 21

# An unfinished session stops being something to continue and becomes one the
# user abandoned. Matches the outer edge of the decay window: past three weeks
# every other lane has let an item go, and a six-month-old session pinning
# "cards left in your session" to the hub is not a prompt, it is furniture.
_CONTINUE_STUDY_MAX_DAYS = 21


@router.get("/overview", response_model=HomeOverviewResponse)
async def get_home_overview(
    recent_limit: int = Query(default=_RECENT_LIMIT, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> HomeOverviewResponse:
    recent_items = await _fetch_recent_items(session, recent_limit)
    active_collections = await _fetch_active_collections(session)
    recent_tags = await _fetch_recent_tags(session)
    continue_reading = await _fetch_continue_reading(session)
    continue_notes = await _fetch_continue_notes(session)
    continue_study = await _fetch_continue_study(session)
    fading_items = await _fetch_fading_items(session)
    weekly_stats = await _fetch_weekly_stats(session)

    recommendations = await recommender_service.get_recommendations(session)
    today_action: TodayAction | None = None
    if recommendations:
        top = recommendations[0]
        if top.kind == "overdue_reviews":
            # the legacy picker produces the same review_cards action enriched
            # with collection context the hero renders -- reuse it, attach evidence
            today_action = await _pick_today_action(session, recent_items)
            if today_action is not None:
                today_action.reasons = top.reasons
                today_action.recommendation_id = top.id
        else:
            today_action = recommender_service.to_today_action(top)
    if today_action is None:
        # no candidate fired: degrade to the original heuristic floor
        today_action = await _pick_today_action(session, recent_items, include_due_cards=False)

    return HomeOverviewResponse(
        today_action=today_action,
        recent_items=recent_items,
        active_collections=active_collections,
        recent_tags=recent_tags,
        continue_reading=continue_reading,
        continue_notes=continue_notes,
        continue_study=continue_study,
        fading_items=fading_items,
        weekly_stats=weekly_stats,
        recommendations=recommendations[1:],
    )


@router.post("/recommendations/{feedback_id}/dismiss", status_code=204)
async def dismiss_recommendation(
    feedback_id: str, session: AsyncSession = Depends(get_db)
) -> Response:
    if not await recommender_service.mark_dismissed(session, feedback_id):
        raise HTTPException(status_code=404, detail="recommendation not found")
    return Response(status_code=204)


@router.post("/recommendations/{feedback_id}/acted", status_code=204)
async def act_on_recommendation(
    feedback_id: str, session: AsyncSession = Depends(get_db)
) -> Response:
    if not await recommender_service.mark_acted(session, feedback_id):
        raise HTTPException(status_code=404, detail="recommendation not found")
    return Response(status_code=204)


async def _fetch_recent_items(session: AsyncSession, limit: int) -> list[RecentItem]:
    rows = await HomeRepo(session).recent_items(limit)
    return [
        RecentItem(
            member_type=row[0],
            member_id=row[1],
            title=row[2] or "(untitled)",
            preview=row[3],
            last_meaningful_at=row[4],
        )
        for row in rows
    ]


async def _fetch_active_collections(session: AsyncSession) -> list[ActiveCollection]:
    repo = HomeRepo(session)
    rows = await repo.active_collections(_ACTIVE_COLLECTIONS_LIMIT)
    if not rows:
        return []
    col_ids = [r[0] for r in rows]
    fc_by_col = await repo.collection_card_counts(col_ids)
    due_by_col = await repo.collection_due_counts(col_ids)
    return [
        ActiveCollection(
            id=r[0],
            name=r[1],
            color=r[2],
            document_count=int(r[3] or 0),
            note_count=int(r[4] or 0),
            flashcard_count=fc_by_col.get(r[0], 0),
            due_card_count=due_by_col.get(r[0], 0),
        )
        for r in rows
    ]


async def _fetch_recent_tags(session: AsyncSession) -> list[RecentTag]:
    rows = await HomeRepo(session).recent_tags(_RECENT_TAGS_LIMIT)
    return [
        RecentTag(
            id=r[0],
            display_name=r[1],
            document_count=int(r[2] or 0),
            note_count=int(r[3] or 0),
        )
        for r in rows
    ]


async def _pick_today_action(
    session: AsyncSession, recent_items: list[RecentItem], *, include_due_cards: bool = True
) -> TodayAction | None:
    """Heuristic priority: review-cards > continue-reading > resume-note > None.

    The hub renders whatever wins; it never has to pick between options.
    include_due_cards=False when called as the recommender's fallback floor:
    due cards are the recommender's signal there, and re-emitting them here
    would resurrect a dismissed recommendation.
    """
    repo = HomeRepo(session)
    # 1. Due flashcards beat everything -- spaced repetition is time-sensitive.
    due_count = await repo.due_card_count() if include_due_cards else 0
    if due_count > 0:
        top_col = await repo.collection_with_most_due()
        return TodayAction(
            kind="review_cards",
            target_id=None,
            label=f"Review {due_count} {'card' if due_count == 1 else 'cards'} due",
            count=due_count,
            collection_id=top_col[0] if top_col else None,
            collection_name=top_col[1] if top_col else None,
            collection_color=top_col[2] if top_col else None,
            scoped_count=int(top_col[3]) if top_col else None,
        )
    # 2. Continue reading the most-recently-touched document if its progress < 1.0.
    for item in recent_items:
        if item.member_type != "document":
            continue
        total, read = await repo.reading_progress(item.member_id)
        if total == 0 or read < total:
            return TodayAction(
                kind="continue_reading",
                target_id=item.member_id,
                label=f"Continue reading: {item.title}",
                count=None,
            )
    # 3. Otherwise nudge back to the most-recent note.
    for item in recent_items:
        if item.member_type == "note":
            return TodayAction(
                kind="resume_note",
                target_id=item.member_id,
                label=f"Resume note: {item.title}",
                count=None,
            )
    return None


async def _fetch_continue_reading(session: AsyncSession) -> list[ContinueReadingItem]:
    """Docs the user is mid-way through and has touched recently.

    Filters: section_count > 0 (we can compute progress), read_count > 0
    (they've actually started), read_count < section_count (not finished).
    Ranks by content_activity recency so warm context wins over stale.
    """
    rows = await HomeRepo(session).recently_active_documents(30)
    out: list[ContinueReadingItem] = []
    for row in rows:
        total = int(row[4] or 0)
        read = int(row[5] or 0)
        if total <= 0 or read <= 0 or read >= total:
            continue
        out.append(
            ContinueReadingItem(
                document_id=row[0],
                title=row[1] or "(untitled)",
                reading_progress_pct=round(read / total, 3),
                sections_read=read,
                sections_total=total,
                last_meaningful_at=row[2],
                word_count=int(row[3] or 0) or None,
            )
        )
        if len(out) >= _CONTINUE_READING_LIMIT:
            break
    return out


async def _fetch_continue_notes(session: AsyncSession) -> list[ContinueNoteItem]:
    """Notes touched recently, most recent first.

    Ranked by content_activity rather than notes.updated_at: ActivityService
    debounces note edits, so its row is the last *meaningful* edit where
    updated_at moves on every autosave.
    """
    rows = await HomeRepo(session).recently_active_notes(_CONTINUE_NOTES_LIMIT)
    return [
        ContinueNoteItem(
            note_id=row[0],
            title=row[1] or "(untitled)",
            last_meaningful_at=row[2],
        )
        for row in rows
    ]


async def _fetch_continue_study(session: AsyncSession) -> ContinueStudyItem | None:
    """The most recent study session that was never ended.

    A session with no `ended_at` is one the user walked away from; its stored
    queue is what resume replays. A session whose queue is exhausted is finished
    in everything but bookkeeping and is not offered, and neither is one older
    than the decay window.
    """
    row = await HomeRepo(session).latest_unended_session(_CONTINUE_STUDY_MAX_DAYS)
    if row is None:
        return None

    planned = row[2]
    if isinstance(planned, str):
        import json  # noqa: PLC0415

        try:
            planned = json.loads(planned)
        except ValueError:
            planned = None
    remaining = len(planned or []) - int(row[3] or 0)
    if remaining <= 0:
        return None

    return ContinueStudyItem(
        session_id=row[0],
        mode=row[1],
        cards_remaining=remaining,
        started_at=row[4],
    )


async def _fetch_fading_items(session: AsyncSession) -> list[FadingItem]:
    """Content touched 7-21 days ago and not since."""
    rows = await HomeRepo(session).fading_items(_FADING_MIN_DAYS, _FADING_MAX_DAYS, _FADING_LIMIT)
    return [
        FadingItem(
            member_type=row[0],
            member_id=row[1],
            title=row[2] or "(untitled)",
            last_meaningful_at=row[3],
            days_since=int(row[4] or 0),
        )
        for row in rows
    ]


async def _fetch_weekly_stats(session: AsyncSession) -> WeeklyStats:
    """The last 7 days in one line."""
    repo = HomeRepo(session)
    return WeeklyStats(
        minutes_studied=round(await repo.week_study_minutes()),
        cards_reviewed=await repo.week_cards_reviewed(),
        notes_written=await repo.week_notes_written(),
        docs_touched=await repo.week_documents_read(),
        seconds_by_activity=await TimeOnTaskService(session).seconds_by_activity(days=7),
    )
