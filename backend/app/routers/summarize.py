"""POST /summarize/{document_id} — SSE streaming summarization endpoint."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel
from app.services.summarizer import SummarizationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/summarize", tags=["summarize"])


class SummarizeRequest(BaseModel):
    mode: Literal["one_sentence", "executive", "detailed", "conversation"]
    model: str | None = None


@router.post("/{document_id}")
async def summarize_document(document_id: str, req: SummarizeRequest) -> StreamingResponse:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    svc = SummarizationService()
    return StreamingResponse(
        svc.stream_summary(document_id, req.mode, req.model),
        media_type="text/event-stream",
    )
