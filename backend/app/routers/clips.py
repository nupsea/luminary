"""CRUD endpoints for passage clips (Reading Journal).

Routes: POST /clips, GET /clips, PATCH /clips/{id}, DELETE /clips/{id}
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ClipModel
from app.services.repo_helpers import get_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ClipCreateRequest(BaseModel):
    document_id: str
    section_id: str | None = None
    section_heading: str | None = None
    pdf_page_number: int | None = None
    selected_text: str = Field(..., min_length=1)
    user_note: str = ""


class ClipPatchRequest(BaseModel):
    user_note: str


class ClipResponse(BaseModel):
    id: str
    document_id: str
    section_id: str | None
    section_heading: str | None
    pdf_page_number: int | None
    selected_text: str
    user_note: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(clip: ClipModel) -> ClipResponse:
    return ClipResponse(
        id=clip.id,
        document_id=clip.document_id,
        section_id=clip.section_id,
        section_heading=clip.section_heading,
        pdf_page_number=clip.pdf_page_number,
        selected_text=clip.selected_text,
        user_note=clip.user_note,
        created_at=clip.created_at,
        updated_at=clip.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=ClipResponse, status_code=201)
async def create_clip(
    req: ClipCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> ClipResponse:
    """Create a new passage clip."""
    clip = ClipModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        section_id=req.section_id,
        section_heading=req.section_heading,
        pdf_page_number=req.pdf_page_number,
        selected_text=req.selected_text,
        user_note=req.user_note,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(clip)
    await session.commit()
    await session.refresh(clip)
    logger.info("Created clip clip_id=%s document_id=%s", clip.id, clip.document_id)
    return _to_response(clip)


@router.get("", response_model=list[ClipResponse])
async def list_clips(
    document_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[ClipResponse]:
    """List clips, optionally filtered by document_id. Newest first."""
    stmt = select(ClipModel).order_by(ClipModel.created_at.desc())
    if document_id:
        stmt = stmt.where(ClipModel.document_id == document_id)
    result = await session.execute(stmt)
    return [_to_response(c) for c in result.scalars().all()]


@router.patch("/{clip_id}", response_model=ClipResponse)
async def patch_clip(
    clip_id: str,
    req: ClipPatchRequest,
    session: AsyncSession = Depends(get_db),
) -> ClipResponse:
    """Update the user_note on a clip."""
    clip = await get_or_404(session, ClipModel, clip_id, name="Clip")
    clip.user_note = req.user_note
    clip.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(clip)
    logger.debug("Patched clip clip_id=%s", clip_id)
    return _to_response(clip)


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(
    clip_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a clip by ID. Returns 404 if not found."""
    await get_or_404(session, ClipModel, clip_id, name="Clip")
    await session.execute(delete(ClipModel).where(ClipModel.id == clip_id))
    await session.commit()
    logger.info("Deleted clip clip_id=%s", clip_id)
