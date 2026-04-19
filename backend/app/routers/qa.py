"""POST /qa — SSE streaming grounded Q&A endpoint."""

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
    web_enabled: bool = False  # optional web augmentation (S142)


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
