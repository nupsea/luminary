"""POST /qa — SSE streaming grounded Q&A endpoint."""

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.qa import get_qa_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["qa"])


class QARequest(BaseModel):
    question: str
    document_ids: list[str] | None = None
    scope: Literal["single", "all"] = "all"
    model: str | None = None


@router.post("")
async def ask_question(req: QARequest) -> StreamingResponse:
    svc = get_qa_service()
    return StreamingResponse(
        svc.stream_answer(req.question, req.document_ids, req.scope, req.model),
        media_type="text/event-stream",
    )
