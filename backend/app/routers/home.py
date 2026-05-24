"""Luminary home hub overview (plan 2E.8).

GET /home/overview is the single-fetch contract for the hub UI. It composes
recent-activity, active-collections, recent-tags, and a today_action CTA so
the hub never makes a follow-up call per section.

Reads only -- the only writer of content_activity is ActivityService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.home import (
    ActiveCollection,
    ContinueReadingItem,
    FadingItem,
    HomeOverviewResponse,
    RecentItem,
    RecentTag,
    TodayAction,
    WeeklyStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/home", tags=["home"])


_RECENT_LIMIT = 10
_ACTIVE_COLLECTIONS_LIMIT = 4
_RECENT_TAGS_LIMIT = 6
_CONTINUE_READING_LIMIT = 3
_FADING_LIMIT = 3
# Decay window: items last touched between 7 and 21 days ago count as
# fading. Inside 7d still feels "current"; past 21d the user has likely
# moved on, surfacing it as a refresher gets noisy.
_FADING_MIN_DAYS = 7
_FADING_MAX_DAYS = 21


@router.get("/overview", response_model=HomeOverviewResponse)
async def get_home_overview(
    recent_limit: int = Query(default=_RECENT_LIMIT, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> HomeOverviewResponse:
    recent_items = await _fetch_recent_items(session, recent_limit)
    active_collections = await _fetch_active_collections(session)
    recent_tags = await _fetch_recent_tags(session)
    continue_reading = await _fetch_continue_reading(session)
    fading_items = await _fetch_fading_items(session)
    weekly_stats = await _fetch_weekly_stats(session)
    today_action = await _pick_today_action(session, recent_items)
    return HomeOverviewResponse(
        today_action=today_action,
        recent_items=recent_items,
        active_collections=active_collections,
        recent_tags=recent_tags,
        continue_reading=continue_reading,
        fading_items=fading_items,
        weekly_stats=weekly_stats,
    )


async def _fetch_recent_items(session: AsyncSession, limit: int) -> list[RecentItem]:
    # UNION the doc and note paths against the same activity feed so a single
    # ORDER BY interleaves them by last_meaningful_at.
    rows = (
        await session.execute(
            text(
                """
                SELECT 'document' AS member_type, ca.member_id, d.title AS title,
                       NULL AS preview, ca.last_meaningful_at
                FROM content_activity ca
                JOIN documents d ON d.id = ca.member_id
                WHERE ca.member_type = 'document'
                UNION ALL
                SELECT 'note' AS member_type, ca.member_id,
                       COALESCE(NULLIF(n.title, ''), substr(n.content, 1, 60)) AS title,
                       substr(n.content, 1, 120) AS preview,
                       ca.last_meaningful_at
                FROM content_activity ca
                JOIN notes n ON n.id = ca.member_id
                WHERE ca.member_type = 'note' AND n.archived = 0
                ORDER BY last_meaningful_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).all()
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
    # Order collections by the most-recent activity timestamp of any member.
    # A collection with no touched member falls back to its created_at via the
    # COALESCE so the first-time-user state surfaces newly-created collections.
    rows = (
        await session.execute(
            text(
                """
                SELECT c.id, c.name, c.color,
                       SUM(CASE WHEN cm.member_type = 'document' THEN 1 ELSE 0 END) AS doc_count,
                       SUM(CASE WHEN cm.member_type = 'note' THEN 1 ELSE 0 END) AS note_count,
                       COALESCE(MAX(ca.last_meaningful_at), c.created_at) AS sort_key
                FROM collections c
                LEFT JOIN collection_members cm ON cm.collection_id = c.id
                LEFT JOIN content_activity ca
                       ON ca.member_id = cm.member_id AND ca.member_type = cm.member_type
                GROUP BY c.id, c.name, c.color, c.created_at
                ORDER BY sort_key DESC
                LIMIT :limit
                """
            ),
            {"limit": _ACTIVE_COLLECTIONS_LIMIT},
        )
    ).all()
    if not rows:
        return []
    # Flashcard counts come from a separate query so the LEFT JOIN above
    # doesn't multiply the GROUP BY rows by card count.
    col_ids = [r[0] for r in rows]
    placeholders = ",".join(f":c{i}" for i in range(len(col_ids)))
    params = {f"c{i}": cid for i, cid in enumerate(col_ids)}
    fc_rows = (
        await session.execute(
            text(
                f"""
                SELECT cm.collection_id, COUNT(DISTINCT fc.id)
                FROM collection_members cm
                JOIN flashcards fc ON (
                    (cm.member_type = 'document' AND fc.document_id = cm.member_id)
                    OR (cm.member_type = 'note' AND fc.note_id = cm.member_id)
                )
                WHERE cm.collection_id IN ({placeholders})
                GROUP BY cm.collection_id
                """
            ),
            params,
        )
    ).all()
    fc_by_col = {cid: count for cid, count in fc_rows}
    return [
        ActiveCollection(
            id=r[0],
            name=r[1],
            color=r[2],
            document_count=int(r[3] or 0),
            note_count=int(r[4] or 0),
            flashcard_count=int(fc_by_col.get(r[0], 0)),
        )
        for r in rows
    ]


async def _fetch_recent_tags(session: AsyncSession) -> list[RecentTag]:
    rows = (
        await session.execute(
            text(
                """
                SELECT t.id, t.display_name,
                       (SELECT COUNT(DISTINCT document_id)
                        FROM document_tag_index WHERE tag_full = t.id) AS doc_count,
                       (SELECT COUNT(DISTINCT note_id)
                        FROM note_tag_index WHERE tag_full = t.id) AS note_count
                FROM canonical_tags t
                ORDER BY t.usage_count DESC
                LIMIT :limit
                """
            ),
            {"limit": _RECENT_TAGS_LIMIT},
        )
    ).all()
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
    session: AsyncSession, recent_items: list[RecentItem]
) -> TodayAction | None:
    """Heuristic priority: review-cards > continue-reading > resume-note > None.

    The hub renders whatever wins; it never has to pick between options.
    """
    # 1. Due flashcards beat everything -- spaced repetition is time-sensitive.
    due_row = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM flashcards "
                "WHERE due_date IS NOT NULL AND due_date <= datetime('now')"
            )
        )
    ).first()
    due_count = int(due_row[0]) if due_row else 0
    if due_count > 0:
        return TodayAction(
            kind="review_cards",
            target_id=None,
            label=f"Review {due_count} {'card' if due_count == 1 else 'cards'} due",
            count=due_count,
        )
    # 2. Continue reading the most-recently-touched document if its progress < 1.0.
    for item in recent_items:
        if item.member_type != "document":
            continue
        prog_row = (
            await session.execute(
                text(
                    "SELECT "
                    " (SELECT COUNT(*) FROM sections WHERE document_id = :d) AS total, "
                    " (SELECT COUNT(*) FROM reading_progress WHERE document_id = :d) AS read"
                ),
                {"d": item.member_id},
            )
        ).first()
        if prog_row is None:
            continue
        total = int(prog_row[0] or 0)
        read = int(prog_row[1] or 0)
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
    rows = (
        await session.execute(
            text(
                """
                SELECT
                  d.id, d.title, ca.last_meaningful_at,
                  (SELECT COUNT(*) FROM sections WHERE document_id = d.id) AS total,
                  (SELECT COUNT(*) FROM reading_progress WHERE document_id = d.id) AS read
                FROM content_activity ca
                JOIN documents d ON d.id = ca.member_id
                WHERE ca.member_type = 'document'
                ORDER BY ca.last_meaningful_at DESC
                LIMIT 30
                """
            )
        )
    ).all()
    out: list[ContinueReadingItem] = []
    for row in rows:
        total = int(row[3] or 0)
        read = int(row[4] or 0)
        if total <= 0 or read <= 0 or read >= total:
            continue
        out.append(
            ContinueReadingItem(
                document_id=row[0],
                title=row[1] or "(untitled)",
                reading_progress_pct=round(read / total, 3),
                last_meaningful_at=row[2],
            )
        )
        if len(out) >= _CONTINUE_READING_LIMIT:
            break
    return out


async def _fetch_fading_items(session: AsyncSession) -> list[FadingItem]:
    """Content touched 7-21 days ago and not since.

    Uses content_activity directly (its row IS the most-recent touch by
    construction). julianday math keeps the SQL portable across SQLite
    builds; we cast back to whole days for the response.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT 'document' AS t, ca.member_id, d.title AS title,
                       ca.last_meaningful_at,
                       CAST(julianday('now') - julianday(ca.last_meaningful_at)
                            AS INTEGER) AS days_since
                FROM content_activity ca
                JOIN documents d ON d.id = ca.member_id
                WHERE ca.member_type = 'document'
                  AND ca.last_meaningful_at <= datetime('now', :min_days)
                  AND ca.last_meaningful_at >= datetime('now', :max_days)
                UNION ALL
                SELECT 'note' AS t, ca.member_id,
                       COALESCE(NULLIF(n.title, ''), substr(n.content, 1, 60)) AS title,
                       ca.last_meaningful_at,
                       CAST(julianday('now') - julianday(ca.last_meaningful_at)
                            AS INTEGER) AS days_since
                FROM content_activity ca
                JOIN notes n ON n.id = ca.member_id
                WHERE ca.member_type = 'note' AND n.archived = 0
                  AND ca.last_meaningful_at <= datetime('now', :min_days)
                  AND ca.last_meaningful_at >= datetime('now', :max_days)
                ORDER BY last_meaningful_at ASC
                LIMIT :limit
                """
            ),
            {
                "min_days": f"-{_FADING_MIN_DAYS} days",
                "max_days": f"-{_FADING_MAX_DAYS} days",
                "limit": _FADING_LIMIT,
            },
        )
    ).all()
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
    """Aggregate the last 7 days into a single one-line summary.

    Each measure is a separate query rather than one giant subquery
    block; SQLite optimizes them independently and the code stays legible.
    """
    minutes_row = (
        await session.execute(
            text(
                """
                SELECT COALESCE(
                  SUM(
                    (julianday(ended_at) - julianday(started_at)) * 24 * 60
                  ), 0
                )
                FROM study_sessions
                WHERE ended_at IS NOT NULL
                  AND started_at >= datetime('now', '-7 days')
                """
            )
        )
    ).first()
    cards_row = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM review_events "
                "WHERE reviewed_at >= datetime('now', '-7 days')"
            )
        )
    ).first()
    notes_row = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM notes "
                "WHERE archived = 0 AND created_at >= datetime('now', '-7 days')"
            )
        )
    ).first()
    docs_row = (
        await session.execute(
            text(
                "SELECT COUNT(DISTINCT member_id) FROM content_activity "
                "WHERE member_type = 'document' "
                "  AND last_meaningful_at >= datetime('now', '-7 days')"
            )
        )
    ).first()
    return WeeklyStats(
        minutes_studied=int(round(float(minutes_row[0] or 0))) if minutes_row else 0,
        cards_reviewed=int(cards_row[0] or 0) if cards_row else 0,
        notes_written=int(notes_row[0] or 0) if notes_row else 0,
        docs_touched=int(docs_row[0] or 0) if docs_row else 0,
    )
