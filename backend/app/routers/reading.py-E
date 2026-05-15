"""POST /reading/progress — upsert reading progress for a section.

Reading progress is best-effort: errors on the write path are logged but never
surfaced to the user. The frontend swallows network errors silently.
"""

import logging
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_session_factory
from app.models import DocumentModel
from app.repos.document_repo import DocumentRepo
from app.services.repo_helpers import get_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reading", tags=["reading"])


class ReadingProgressRequest(BaseModel):
    document_id: str
    section_id: str


class ReadingProgressResponse(BaseModel):
    document_id: str
    section_id: str
    view_count: int
    first_seen_at: datetime
    last_seen_at: datetime


@router.post("/progress", response_model=ReadingProgressResponse, status_code=200)
async def upsert_reading_progress(body: ReadingProgressRequest) -> ReadingProgressResponse:
    """Mark a section as seen. Increments view_count on repeat visits.

    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, body.document_id, name="Document")
        repo = DocumentRepo(session)
        result = await repo.upsert_reading_progress(
            document_id=body.document_id,
            section_id=body.section_id,
        )

    logger.info(
        "Reading progress upsert",
        extra={
            "document_id": body.document_id,
            "section_id": body.section_id,
            "view_count": result.view_count,
        },
    )
    return ReadingProgressResponse(
        document_id=result.document_id,
        section_id=result.section_id,
        view_count=result.view_count,
        first_seen_at=result.first_seen_at,
        last_seen_at=result.last_seen_at,
    )
