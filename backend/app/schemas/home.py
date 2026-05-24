"""Schemas for the Luminary home hub overview endpoint (plan 2E.8).

A single contract sized so the hub renders from one response: today_action
(the suggested first move), recent_items (interleaved doc + note feed),
active_collections (recently-touched collections with mini-stats), and
recent_tags (top tag chips). No per-section follow-up fetches.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TodayAction(BaseModel):
    """Single, dominant CTA on the hub. Picked by the backend so the UI
    has one shape regardless of which signal was strongest."""

    kind: Literal["review_cards", "continue_reading", "resume_note"]
    target_id: str | None = None  # document_id for read; note_id for resume
    label: str
    count: int | None = None  # e.g. due-card count for kind='review_cards'


class RecentItem(BaseModel):
    """One row in the interleaved recent-activity feed."""

    member_type: Literal["document", "note"]
    member_id: str
    title: str
    preview: str | None = None  # first ~120 chars of note content; null for docs
    last_meaningful_at: datetime


class ActiveCollection(BaseModel):
    id: str
    name: str
    color: str
    document_count: int
    note_count: int
    flashcard_count: int


class RecentTag(BaseModel):
    id: str
    display_name: str
    # Split usage so the hub chip can show "8d / 6n" (plan 2E.7).
    document_count: int
    note_count: int


class ContinueReadingItem(BaseModel):
    """A doc the user has momentum on -- started, not finished, recently touched."""

    document_id: str
    title: str
    reading_progress_pct: float  # 0..1
    last_meaningful_at: datetime


class FadingItem(BaseModel):
    """Content the user engaged with 7-21 days ago and not since.

    Surfaces the decay-risk corner of the library that a recency feed
    deliberately hides. Hub copy frames it as "worth a refresher?" rather
    than as a guilt trip.
    """

    member_type: Literal["document", "note"]
    member_id: str
    title: str
    last_meaningful_at: datetime
    days_since: int


class WeeklyStats(BaseModel):
    """Foot-of-hub one-line summary for the last 7 days."""

    minutes_studied: int
    cards_reviewed: int
    notes_written: int
    docs_touched: int


class HomeOverviewResponse(BaseModel):
    today_action: TodayAction | None
    recent_items: list[RecentItem]
    active_collections: list[ActiveCollection]
    recent_tags: list[RecentTag]
    # Coach-shaped additions (post-2E.7 redesign).
    continue_reading: list[ContinueReadingItem] = []
    fading_items: list[FadingItem] = []
    weekly_stats: WeeklyStats | None = None


class CollectionTagChip(BaseModel):
    """Tag with usage count restricted to a single collection's members."""

    id: str
    display_name: str
    count: int


class CollectionOverviewResponse(BaseModel):
    """Overview tab on /collections/:id (plan 2E.6).

    Same shape language as the hub but scoped: recent activity only counts
    members of this collection, and tag chips reflect tags applied to
    those members.
    """

    recent_items: list[RecentItem]
    tags: list[CollectionTagChip]
    document_count: int
    note_count: int
    flashcard_count: int
