"""Goals router -- POST /goals, GET /goals, DELETE /goals/{id}, GET /goals/{id}/readiness."""

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.goal_service import GoalService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/goals", tags=["goals"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateGoalRequest(BaseModel):
    document_id: str
    title: str
    target_date: str  # ISO date string: 'YYYY-MM-DD'

    @field_validator("target_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("target_date must be a valid ISO date (YYYY-MM-DD)") from exc
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("document_id must not be empty")
        return v


class GoalResponse(BaseModel):
    id: str
    document_id: str
    title: str
    target_date: str
    created_at: str


class AtRiskCardItem(BaseModel):
    id: str
    question: str
    projected_retention_pct: float


class ReadinessResponse(BaseModel):
    on_track: bool
    projected_retention_pct: float
    at_risk_card_count: int
    at_risk_cards: list[AtRiskCardItem]


# ---------------------------------------------------------------------------
# Endpoints — readiness MUST be registered before /{goal_id} to avoid
# FastAPI matching "readiness" as a goal_id for DELETE.
# ---------------------------------------------------------------------------


@router.get("/{goal_id}/readiness", response_model=ReadinessResponse)
async def get_goal_readiness(goal_id: str, session: AsyncSession = Depends(get_db)):
    """Compute projected retention at target_date for the goal's document."""
    svc = GoalService(session)
    goal = await svc.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    result = await svc.compute_readiness(goal)
    at_risk = [AtRiskCardItem(**c) for c in result["at_risk_cards"]]
    return ReadinessResponse(
        on_track=result["on_track"],
        projected_retention_pct=result["projected_retention_pct"],
        at_risk_card_count=result["at_risk_card_count"],
        at_risk_cards=at_risk,
    )


@router.post("", status_code=201, response_model=GoalResponse)
async def create_goal(body: CreateGoalRequest, session: AsyncSession = Depends(get_db)):
    svc = GoalService(session)
    goal_id = str(uuid.uuid4())
    goal = await svc.create_goal(
        goal_id=goal_id,
        document_id=body.document_id,
        title=body.title,
        target_date=body.target_date,
    )
    return GoalResponse(
        id=goal.id,
        document_id=goal.document_id,
        title=goal.title,
        target_date=goal.target_date,
        created_at=goal.created_at.isoformat(),
    )


@router.get("", response_model=list[GoalResponse])
async def list_goals(session: AsyncSession = Depends(get_db)):
    svc = GoalService(session)
    goals = await svc.list_goals()
    return [
        GoalResponse(
            id=g.id,
            document_id=g.document_id,
            title=g.title,
            target_date=g.target_date,
            created_at=g.created_at.isoformat(),
        )
        for g in goals
    ]


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: str, session: AsyncSession = Depends(get_db)):
    svc = GoalService(session)
    deleted = await svc.delete_goal(goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Goal not found")
