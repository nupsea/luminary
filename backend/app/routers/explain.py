"""POST /explain (SSE streaming) and POST /glossary/{document_id} endpoints."""

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.explain import get_explain_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/explain", tags=["explain"])


class ExplainRequest(BaseModel):
    text: str
    document_id: str
    mode: Literal["plain", "eli5", "analogy", "formal"] = "plain"


@router.post("")
async def explain_text(req: ExplainRequest) -> StreamingResponse:
    """Stream an explanation of the selected text using surrounding document context."""
    svc = get_explain_service()
    return StreamingResponse(
        svc.stream_explain(req.text, req.document_id, req.mode),
        media_type="text/event-stream",
    )


@router.post("/glossary/{document_id}")
async def extract_glossary(document_id: str) -> list[dict]:
    """Extract domain-specific terms from a document and return as a JSON list."""
    svc = get_explain_service()
    return await svc.extract_glossary(document_id)
