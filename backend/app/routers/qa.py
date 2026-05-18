"""POST /qa — SSE streaming grounded Q&A endpoint."""

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.intent import classify_intent_heuristic
from app.services.qa import get_qa_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["qa"])


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QARequest(BaseModel):
    question: str
    document_ids: list[str] | None = None
    scope: Literal["single", "all"] = "all"
    model: str | None = None
    messages: list[ConversationMessage] | None = None  # sliding-window history
    web_enabled: bool = False  # optional web augmentation


class ClassifyOnlyResponse(BaseModel):
    chosen_route: Literal["summary", "graph", "comparative", "search"]
    intent: str
    confidence: float


def _normalize_classify_route(intent: str) -> Literal["summary", "graph", "comparative", "search"]:
    if intent == "summary":
        return "summary"
    if intent == "relational":
        return "graph"
    if intent == "comparative":
        return "comparative"
    return "search"


@router.post("")
async def ask_question(req: QARequest) -> StreamingResponse:
    svc = get_qa_service()
    history = [m.model_dump() for m in req.messages] if req.messages else []
    return StreamingResponse(
        svc.stream_answer(
            req.question,
            req.document_ids,
            req.scope,
            req.model,
            history,
            web_enabled=req.web_enabled,
        ),
        media_type="text/event-stream",
    )


@router.post("/classify-only", response_model=ClassifyOnlyResponse)
async def classify_only(req: QARequest) -> ClassifyOnlyResponse:
    """Classify the chat route without executing retrieval/LLM graph nodes."""
    intent, confidence = classify_intent_heuristic(req.question)
    return ClassifyOnlyResponse(
        chosen_route=_normalize_classify_route(intent),
        intent=intent,
        confidence=confidence,
    )
