"""Engagement router -- streaks, XP, achievements, focus sessions."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import InvalidInput
from app.services.engagement_service import EngagementService
from app.services.time_on_task_service import (
    ACTIVITIES,
    HEARTBEAT_SECONDS,
    TimeOnTaskService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engagement", tags=["engagement"])


class FocusStartRequest(BaseModel):
    duration_minutes: int = 25
    session_type: str = "study"


class HeartbeatRequest(BaseModel):
    # 'document' | 'note' | 'review' | 'study'
    activity: str
    # The document/note/session the time is being spent on, where there is one.
    member_id: str | None = None


class HeartbeatResponse(BaseModel):
    """What this beat was worth, and how often to send the next one.

    `seconds_credited` is 0 for the first beat of a stretch and for one arriving
    after a gap too long to be continuous. The client does not need to act on
    it; it is returned so the accrual is observable rather than opaque.
    """

    seconds_credited: int
    heartbeat_seconds: int


class FocusSessionResponse(BaseModel):
    id: str
    started_at: str
    planned_duration_minutes: int
    session_type: str


# Streak endpoints


_TZ_OFFSET_DESC = (
    "Client's timezone offset from UTC in minutes, matching JS "
    "`Date.getTimezoneOffset()` (positive west of UTC; PDT=420). "
    "When provided, streak / XP / focus buckets use the user's local "
    "date so a session at 11pm doesn't roll over into tomorrow."
)


@router.get("/streak")
async def get_streak(
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = EngagementService(session, tz_offset_minutes=tz_offset_minutes)
    return await svc.get_streak()


# XP endpoints


@router.get("/xp")
async def get_xp(
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = EngagementService(session, tz_offset_minutes=tz_offset_minutes)
    return await svc.get_xp_summary()


@router.get("/xp/history")
async def get_xp_history(
    days: int = Query(default=30, ge=1, le=365),
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    svc = EngagementService(session, tz_offset_minutes=tz_offset_minutes)
    return await svc.get_xp_history(days)


# Achievement endpoints


@router.get("/achievements")
async def get_achievements(session: AsyncSession = Depends(get_db)) -> list[dict]:
    svc = EngagementService(session)
    return await svc.get_achievements()


@router.get("/achievements/recent")
async def get_recent_achievements(
    days: int = Query(default=7, ge=1, le=90),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    svc = EngagementService(session)
    return await svc.get_recent_achievements(days)


# Focus session endpoints


@router.post("/heartbeat")
async def heartbeat(
    req: HeartbeatRequest,
    session: AsyncSession = Depends(get_db),
) -> HeartbeatResponse:
    """Sample of foreground attention, sent by a surface while it is visible.

    The server cannot measure this itself: a reader who opens a document and
    reads for twenty minutes issues one request. What is recorded is time with
    the page open and visible, which is not the same as time spent reading, and
    `docs/metrics.md` requires it be reported as the former.
    """
    try:
        credited = await TimeOnTaskService(session).beat(req.activity, req.member_id)
    except ValueError as exc:
        raise InvalidInput(f"activity must be one of {', '.join(ACTIVITIES)}") from exc
    return HeartbeatResponse(
        seconds_credited=credited,
        heartbeat_seconds=HEARTBEAT_SECONDS,
    )


@router.post("/focus/start")
async def start_focus(
    req: FocusStartRequest,
    session: AsyncSession = Depends(get_db),
) -> FocusSessionResponse:
    svc = EngagementService(session)
    fs = await svc.start_focus_session(req.duration_minutes, req.session_type)
    return FocusSessionResponse(
        id=fs.id,
        started_at=fs.started_at.isoformat(),
        planned_duration_minutes=fs.planned_duration_minutes,
        session_type=fs.session_type,
    )


@router.post("/focus/{session_id}/complete")
async def complete_focus(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = EngagementService(session)
    try:
        return await svc.complete_focus_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/focus/{session_id}/cancel")
async def cancel_focus(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = EngagementService(session)
    try:
        return await svc.cancel_focus_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/focus/today")
async def get_today_sessions(
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    svc = EngagementService(session, tz_offset_minutes=tz_offset_minutes)
    return await svc.get_today_sessions()


@router.get("/focus/stats")
async def get_focus_stats(
    days: int = Query(default=7, ge=1, le=365),
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = EngagementService(session, tz_offset_minutes=tz_offset_minutes)
    return await svc.get_focus_stats(days)
