"""Feynman technique session router (S144).

Routes:
  POST /feynman/sessions              -- create session, return opening message
  POST /feynman/sessions/{id}/message -- stream learner turn via SSE
  POST /feynman/sessions/{id}/complete -- complete session, generate flashcards
  GET  /feynman/sessions              -- list sessions for a document
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.study import (
    RubricCompletenessResponse,
    RubricDimensionResponse,
    TeachbackRubricResponse,
)
from app.services.feynman_service import get_feynman_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feynman", tags=["feynman"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class FeynmanSessionCreateRequest(BaseModel):
    document_id: str
    section_id: str | None = None
    concept: str


class FeynmanSessionResponse(BaseModel):
    id: str
    concept: str
    status: str
    opening_message: str
    created_at: datetime


class FeynmanMessageRequest(BaseModel):
    content: str


class FeynmanCompleteResponse(BaseModel):
    gap_count: int
    flashcard_ids: list[str]
    rubric: TeachbackRubricResponse | None = None  # S156: null when rubric evaluation failed


class FeynmanSessionListItem(BaseModel):
    id: str
    concept: str
    status: str
    gap_count: int
    created_at: datetime
    section_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=FeynmanSessionResponse, status_code=201)
async def create_feynman_session(
    req: FeynmanSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> FeynmanSessionResponse:
    """Create a new Feynman session and return the opening tutor message.

    Returns HTTP 503 if Ollama is unreachable.
    """
    svc = get_feynman_service()
    session_row, opening_message = await svc.create_session(
        document_id=req.document_id,
        section_id=req.section_id,
        concept=req.concept,
        session=db,
    )
    logger.info(
        "POST /feynman/sessions: session_id=%s document_id=%s",
        session_row.id,
        req.document_id,
    )
    return FeynmanSessionResponse(
        id=session_row.id,
        concept=session_row.concept,
        status=session_row.status,
        opening_message=opening_message,
        created_at=session_row.created_at,
    )


@router.post("/sessions/{session_id}/message")
async def post_feynman_message(
    session_id: str,
    req: FeynmanMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream tutor response to a learner message via SSE.

    SSE events:
      data: {"token": "..."}        -- streaming token
      data: {"done": true, "answer": "...", "gaps": [...]}  -- completion
      data: {"error": "llm_unavailable", "message": "..."}  -- if Ollama is down
    """
    svc = get_feynman_service()

    async def event_stream():
        try:
            async for event in svc.stream_turn(session_id, req.content, db):
                yield event
        except HTTPException as exc:
            import json  # noqa: PLC0415

            if exc.status_code == 404:
                yield f"data: {json.dumps({'error': 'not_found', 'message': exc.detail})}\n\n"
            else:
                yield f"data: {json.dumps({'error': 'server_error', 'message': exc.detail})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/sessions/{session_id}/complete", response_model=FeynmanCompleteResponse)
async def complete_feynman_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> FeynmanCompleteResponse:
    """Complete a Feynman session: generate gap flashcards and update objective coverage."""
    svc = get_feynman_service()
    result = await svc.complete_session(session_id, db)
    logger.info(
        "POST /feynman/sessions/%s/complete: gap_count=%d flashcards=%d",
        session_id,
        result["gap_count"],
        len(result["flashcard_ids"]),
    )
    rubric_response: TeachbackRubricResponse | None = None
    rubric_dict = result.get("rubric")
    if rubric_dict is not None:
        try:
            rubric_response = TeachbackRubricResponse(
                accuracy=RubricDimensionResponse(**rubric_dict["accuracy"]),
                completeness=RubricCompletenessResponse(**rubric_dict["completeness"]),
                clarity=RubricDimensionResponse(**rubric_dict["clarity"]),
            )
        except (KeyError, TypeError, ValueError):
            rubric_response = None

    return FeynmanCompleteResponse(
        gap_count=result["gap_count"],
        flashcard_ids=result["flashcard_ids"],
        rubric=rubric_response,
    )


@router.post("/sessions/{session_id}/model-explanation")
async def generate_model_explanation(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a model-generated explanation for the Feynman session concept via SSE.

    SSE events:
      data: {"token": "..."}                                       -- streaming token
      data: {"done": true, "explanation": "...", "key_points": [...]}  -- completion
      data: {"error": "not_found", "message": "..."}              -- if session missing
      data: {"error": "llm_unavailable", "message": "..."}        -- if Ollama is down
    """
    svc = get_feynman_service()

    async def event_stream():
        async for event in svc.generate_model_explanation(session_id, db):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions", response_model=list[FeynmanSessionListItem])
async def list_feynman_sessions(
    document_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[FeynmanSessionListItem]:
    """Return all Feynman sessions for a document with gap_count and status."""
    svc = get_feynman_service()
    sessions = await svc.list_sessions(document_id, db)
    return [
        FeynmanSessionListItem(
            id=s["id"],
            concept=s["concept"],
            status=s["status"],
            gap_count=s["gap_count"],
            created_at=s["created_at"],
            section_id=s.get("section_id"),
        )
        for s in sessions
    ]
