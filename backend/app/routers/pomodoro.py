"""S208: /pomodoro/* endpoints for the global focus timer.

Thin layer over PomodoroService -- validation in pydantic, transitions in service.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import PomodoroSessionModel
from app.services.pomodoro_service import (
    ActiveSessionExists,
    InvalidTransition,
    PomodoroService,
    SessionNotFound,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pomodoro", tags=["pomodoro"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


SurfaceLiteral = Literal["read", "recall", "write", "explore", "none"]
StatusLiteral = Literal["active", "paused", "completed", "abandoned"]


class StartSessionRequest(BaseModel):
    focus_minutes: int = Field(default=25, ge=1, le=240)
    break_minutes: int = Field(default=5, ge=1, le=120)
    surface: SurfaceLiteral = "none"
    document_id: str | None = None
    deck_id: str | None = None
    goal_id: str | None = None


class SessionResponse(BaseModel):
    id: str
    started_at: str
    completed_at: str | None
    focus_minutes: int
    break_minutes: int
    status: StatusLiteral
    surface: SurfaceLiteral
    document_id: str | None
    deck_id: str | None
    goal_id: str | None
    paused_at: str | None
    pause_accumulated_seconds: int
    created_at: str


class StatsResponse(BaseModel):
    today_count: int
    streak_days: int
    total_completed: int


def _to_response(row: PomodoroSessionModel) -> SessionResponse:
    return SessionResponse(
        id=row.id,
        started_at=row.started_at.isoformat() if row.started_at else "",
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        focus_minutes=row.focus_minutes,
        break_minutes=row.break_minutes,
        status=row.status,  # type: ignore[arg-type]
        surface=row.surface,  # type: ignore[arg-type]
        document_id=row.document_id,
        deck_id=row.deck_id,
        goal_id=row.goal_id,
        paused_at=row.paused_at.isoformat() if row.paused_at else None,
        pause_accumulated_seconds=row.pause_accumulated_seconds,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


# ---------------------------------------------------------------------------
# Endpoints -- order matters: /active and /stats before /{session_id}/...
# ---------------------------------------------------------------------------


@router.get("/active")
async def get_active(session: AsyncSession = Depends(get_db)) -> Response:
    svc = PomodoroService(session)
    row = await svc.get_active_session()
    if row is None:
        return Response(status_code=204)
    return Response(
        content=_to_response(row).model_dump_json(),
        media_type="application/json",
        status_code=200,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_db)) -> StatsResponse:
    svc = PomodoroService(session)
    stats = await svc.get_stats()
    return StatsResponse(**stats)


@router.post("/start", response_model=SessionResponse)
async def start_session(
    body: StartSessionRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionResponse:
    svc = PomodoroService(session)
    try:
        row = await svc.start_session(
            focus_minutes=body.focus_minutes,
            break_minutes=body.break_minutes,
            surface=body.surface,
            document_id=body.document_id,
            deck_id=body.deck_id,
            goal_id=body.goal_id,
        )
    except ActiveSessionExists as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "active or paused session already exists",
                "existing_session_id": exc.existing_id,
            },
        ) from exc
    return _to_response(row)


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def pause(
    session_id: str, session: AsyncSession = Depends(get_db)
) -> SessionResponse:
    svc = PomodoroService(session)
    try:
        row = await svc.pause_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(row)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume(
    session_id: str, session: AsyncSession = Depends(get_db)
) -> SessionResponse:
    svc = PomodoroService(session)
    try:
        row = await svc.resume_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(row)


@router.post("/{session_id}/complete", response_model=SessionResponse)
async def complete(
    session_id: str, session: AsyncSession = Depends(get_db)
) -> SessionResponse:
    svc = PomodoroService(session)
    try:
        row = await svc.complete_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(row)


@router.post("/{session_id}/abandon", response_model=SessionResponse)
async def abandon(
    session_id: str, session: AsyncSession = Depends(get_db)
) -> SessionResponse:
    svc = PomodoroService(session)
    try:
        row = await svc.abandon_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(row)
