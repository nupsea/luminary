"""CRUD endpoints for passage clips (Reading Journal).

Routes: POST /clips, GET /clips, PATCH /clips/{id}, DELETE /clips/{id}

Persistence is delegated to `ClipRepo`; this module owns only the HTTP
contract and DTO mapping.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.models import ClipModel
from app.repos.clip_repo import ClipRepo, get_clip_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])


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


@router.post("", response_model=ClipResponse, status_code=201)
async def create_clip(
    req: ClipCreateRequest,
    repo: ClipRepo = Depends(get_clip_repo),
) -> ClipResponse:
    """Create a new passage clip."""
    clip = await repo.create(
        document_id=req.document_id,
        section_id=req.section_id,
        section_heading=req.section_heading,
        pdf_page_number=req.pdf_page_number,
        selected_text=req.selected_text,
        user_note=req.user_note,
    )
    logger.info("Created clip clip_id=%s document_id=%s", clip.id, clip.document_id)
    return _to_response(clip)


@router.get("", response_model=list[ClipResponse])
async def list_clips(
    document_id: str | None = Query(default=None),
    repo: ClipRepo = Depends(get_clip_repo),
) -> list[ClipResponse]:
    """List clips, optionally filtered by document_id. Newest first."""
    clips = await repo.list(document_id=document_id)
    return [_to_response(c) for c in clips]


@router.patch("/{clip_id}", response_model=ClipResponse)
async def patch_clip(
    clip_id: str,
    req: ClipPatchRequest,
    repo: ClipRepo = Depends(get_clip_repo),
) -> ClipResponse:
    """Update the user_note on a clip."""
    clip = await repo.update_note(clip_id, user_note=req.user_note)
    logger.debug("Patched clip clip_id=%s", clip_id)
    return _to_response(clip)


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(
    clip_id: str,
    repo: ClipRepo = Depends(get_clip_repo),
) -> None:
    """Delete a clip by ID. Returns 404 if not found."""
    await repo.delete(clip_id)
    logger.info("Deleted clip clip_id=%s", clip_id)
