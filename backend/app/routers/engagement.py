"""Engagement router -- streaks, XP, achievements, focus sessions."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.engagement_service import EngagementService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engagement", tags=["engagement"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class FocusStartRequest(BaseModel):
    duration_minutes: int = 25
    session_type: str = "study"


class FocusSessionResponse(BaseModel):
    id: str
    started_at: str
    planned_duration_minutes: int
    session_type: str


# ---------------------------------------------------------------------------
# Streak endpoints
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# XP endpoints
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Achievement endpoints
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Focus session endpoints
# ---------------------------------------------------------------------------


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
