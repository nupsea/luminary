"""GET /chat/confusion-signals and GET /chat/explorations -- DB-only, no LLM, < 200ms."""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.confusion_detector import get_confusion_detector
from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ConfusionSignalResponse(BaseModel):
    concept: str
    count: int
    last_asked: str


class ExplorationSuggestion(BaseModel):
    text: str
    entity_names: list[str]


@router.get("/confusion-signals", response_model=list[ConfusionSignalResponse])
async def get_confusion_signals(
    session: AsyncSession = Depends(get_db),
) -> list[ConfusionSignalResponse]:
    """Return top concepts the learner has asked about >= 3 times in the last 30 days."""
    signals = await get_confusion_detector().detect(session)
    return [ConfusionSignalResponse(**s) for s in signals]


@router.get("/explorations", response_model=list[ExplorationSuggestion])
async def get_explorations(
    document_id: str = Query(..., description="Document ID to derive entity-pair suggestions for"),
) -> list[ExplorationSuggestion]:
    """Return up to 5 proactive exploration suggestions from Kuzu RELATED_TO entity pairs.

    Suggestions are derived from entity pairs that co-appear in the given document and
    are connected by a RELATED_TO edge.  Returns an empty list when no such pairs exist.
    """
    pairs = get_graph_service().get_related_entity_pairs_for_document(document_id, limit=5)
    suggestions: list[ExplorationSuggestion] = []
    for name_a, name_b, label, _conf in pairs:
        display_a = name_a.title()
        display_b = name_b.title()
        if label:
            text = f"What is the {label} between {display_a} and {display_b}?"
        else:
            text = f"How is {display_a} related to {display_b}?"
        suggestions.append(ExplorationSuggestion(text=text, entity_names=[name_a, name_b]))
    logger.debug(
        "explorations: doc=%s returned %d suggestions", document_id, len(suggestions)
    )
    return suggestions
