"""S210: typed learning goals router.

Endpoints (literal paths registered before parametric per FastAPI ordering rule):
- GET /goals?status=...    list goals optionally filtered by status
- POST /goals              create a goal
- GET /goals/{id}          get one goal
- PATCH /goals/{id}        update mutable fields (title, description, target_value, target_unit)
- POST /goals/{id}/archive set status='archived'
- POST /goals/{id}/complete set status='completed' and completed_at=now
- GET /goals/{id}/progress type-dispatched progress aggregation
- POST /goals/{id}/sessions/{session_id}    link a Pomodoro session
- DELETE /goals/{id}/sessions/{session_id}  unlink a session
- DELETE /goals/{id}       delete the goal; sets goal_id=NULL on linked sessions

Replaces the old document-centric /goals API (FSRS readiness projection). The new
schema uses typed goals (studying|read|recall|write|explore) with optional document/deck/
collection links; progress is aggregated from completed Pomodoro sessions plus
domain-specific tables (review_events, notes, qa_history).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import LearningGoalModel
from app.services.goal_service import (
    GoalNotFound,
    InvalidGoalType,
    InvalidTargetUnit,
    LearningGoalsService,
    SessionNotFound,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/goals", tags=["goals"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


GoalTypeLiteral = Literal["studying", "read", "recall", "write", "explore"]
TargetUnitLiteral = Literal["minutes", "pages", "cards", "notes", "turns"]
StatusLiteral = Literal["active", "paused", "completed", "archived"]


class CreateGoalRequest(BaseModel):
    title: str
    goal_type: GoalTypeLiteral
    target_value: int | None = Field(default=None, ge=1)
    target_unit: TargetUnitLiteral | None = None
    document_id: str | None = None
    deck_id: str | None = None
    collection_id: str | None = None
    description: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v


class UpdateGoalRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    target_value: int | None = Field(default=None, ge=1)
    target_unit: TargetUnitLiteral | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v


class GoalResponse(BaseModel):
    id: str
    title: str
    description: str | None
    goal_type: str
    target_value: int | None
    target_unit: str | None
    document_id: str | None
    deck_id: str | None
    collection_id: str | None
    status: str
    created_at: str
    completed_at: str | None


class ProgressResponse(BaseModel):
    goal_id: str
    goal_type: str
    metrics: dict[str, Any]


class LinkedSessionResponse(BaseModel):
    id: str
    started_at: str
    completed_at: str | None
    status: str
    surface: str
    focus_minutes: int


def _to_response(row: LearningGoalModel) -> GoalResponse:
    return GoalResponse(
        id=row.id,
        title=row.title,
        description=row.description,
        goal_type=row.goal_type,
        target_value=row.target_value,
        target_unit=row.target_unit,
        document_id=row.document_id,
        deck_id=row.deck_id,
        collection_id=row.collection_id,
        status=row.status,
        created_at=row.created_at.isoformat() if row.created_at else "",
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


# ---------------------------------------------------------------------------
# Endpoints -- literal paths first, then parametric
# ---------------------------------------------------------------------------


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    status: StatusLiteral | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[GoalResponse]:
    svc = LearningGoalsService(session)
    rows = await svc.list_goals(status_filter=status)
    return [_to_response(r) for r in rows]


@router.post("", response_model=GoalResponse)
async def create_goal(
    body: CreateGoalRequest, session: AsyncSession = Depends(get_db)
) -> GoalResponse:
    svc = LearningGoalsService(session)
    try:
        row = await svc.create_goal(
            title=body.title,
            goal_type=body.goal_type,
            target_value=body.target_value,
            target_unit=body.target_unit,
            document_id=body.document_id,
            deck_id=body.deck_id,
            collection_id=body.collection_id,
            description=body.description,
        )
    except (InvalidGoalType, InvalidTargetUnit, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(row)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: str, session: AsyncSession = Depends(get_db)
) -> GoalResponse:
    svc = LearningGoalsService(session)
    row = await svc.get_goal(goal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return _to_response(row)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: str,
    body: UpdateGoalRequest,
    session: AsyncSession = Depends(get_db),
) -> GoalResponse:
    svc = LearningGoalsService(session)
    try:
        row = await svc.update_goal(
            goal_id=goal_id,
            title=body.title,
            description=body.description,
            target_value=body.target_value,
            target_unit=body.target_unit,
        )
    except GoalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidTargetUnit, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(row)


@router.post("/{goal_id}/archive", response_model=GoalResponse)
async def archive_goal(
    goal_id: str, session: AsyncSession = Depends(get_db)
) -> GoalResponse:
    svc = LearningGoalsService(session)
    try:
        row = await svc.archive_goal(goal_id)
    except GoalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(row)


@router.post("/{goal_id}/complete", response_model=GoalResponse)
async def complete_goal(
    goal_id: str, session: AsyncSession = Depends(get_db)
) -> GoalResponse:
    svc = LearningGoalsService(session)
    try:
        row = await svc.complete_goal(goal_id)
    except GoalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(row)


@router.get("/{goal_id}/progress", response_model=ProgressResponse)
async def get_progress(
    goal_id: str, session: AsyncSession = Depends(get_db)
) -> ProgressResponse:
    svc = LearningGoalsService(session)
    try:
        metrics = await svc.compute_progress(goal_id)
        goal = await svc.get_goal(goal_id)
    except GoalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return ProgressResponse(goal_id=goal.id, goal_type=goal.goal_type, metrics=metrics)


@router.get("/{goal_id}/sessions", response_model=list[LinkedSessionResponse])
async def list_linked_sessions(
    goal_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> list[LinkedSessionResponse]:
    svc = LearningGoalsService(session)
    goal = await svc.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    rows = await svc.list_linked_sessions(goal_id, limit=limit)
    return [
        LinkedSessionResponse(
            id=r.id,
            started_at=r.started_at.isoformat() if r.started_at else "",
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            status=r.status,
            surface=r.surface,
            focus_minutes=r.focus_minutes,
        )
        for r in rows
    ]


@router.post("/{goal_id}/sessions/{session_id}", status_code=200)
async def link_session(
    goal_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = LearningGoalsService(session)
    try:
        await svc.link_session(goal_id, session_id)
    except GoalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"goal_id": goal_id, "session_id": session_id, "linked": True}


@router.delete("/{goal_id}/sessions/{session_id}", status_code=200)
async def unlink_session(
    goal_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = LearningGoalsService(session)
    try:
        await svc.unlink_session(goal_id, session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"goal_id": goal_id, "session_id": session_id, "linked": False}


@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str, session: AsyncSession = Depends(get_db)
) -> Response:
    svc = LearningGoalsService(session)
    deleted = await svc.delete_goal(goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="goal not found")
    return Response(status_code=204)
