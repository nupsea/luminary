"""GET /chat/confusion-signals -- DB-only, no LLM, < 200ms."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.confusion_detector import get_confusion_detector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ConfusionSignalResponse(BaseModel):
    concept: str
    count: int
    last_asked: str


@router.get("/confusion-signals", response_model=list[ConfusionSignalResponse])
async def get_confusion_signals(
    session: AsyncSession = Depends(get_db),
) -> list[ConfusionSignalResponse]:
    """Return top concepts the learner has asked about >= 3 times in the last 30 days."""
    signals = await get_confusion_detector().detect(session)
    return [ConfusionSignalResponse(**s) for s in signals]
