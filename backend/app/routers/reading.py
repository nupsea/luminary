"""POST /reading/progress — upsert reading progress for a section.

Reading progress is best-effort: errors on the write path are logged but never
surfaced to the user. The frontend swallows network errors silently.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, ReadingProgressModel

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
        doc = (
            await session.execute(
                select(DocumentModel.id).where(DocumentModel.id == body.document_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        now = datetime.now(UTC)

        existing = (
            await session.execute(
                select(ReadingProgressModel).where(
                    ReadingProgressModel.document_id == body.document_id,
                    ReadingProgressModel.section_id == body.section_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            row = ReadingProgressModel(
                id=str(uuid.uuid4()),
                document_id=body.document_id,
                section_id=body.section_id,
                first_seen_at=now,
                last_seen_at=now,
                view_count=1,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            result = row
        else:
            existing.last_seen_at = now
            existing.view_count += 1
            await session.commit()
            await session.refresh(existing)
            result = existing

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
