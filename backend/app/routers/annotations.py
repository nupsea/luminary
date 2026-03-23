"""POST /annotations, GET /annotations, DELETE /annotations/{id}.

Persistent text highlights anchored to document sections. No document validation
on write — annotation storage is decoupled from document lifecycle to keep the
router simple.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import AnnotationModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/annotations", tags=["annotations"])


class AnnotationCreateRequest(BaseModel):
    document_id: str
    section_id: str
    chunk_id: str | None = None
    selected_text: str
    start_offset: int
    end_offset: int
    color: Literal["yellow", "green", "blue", "pink"] = "yellow"
    note_text: str | None = None
    page_number: int | None = None


class AnnotationResponse(BaseModel):
    id: str
    document_id: str
    section_id: str
    chunk_id: str | None
    selected_text: str
    start_offset: int
    end_offset: int
    color: str
    note_text: str | None
    page_number: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("", response_model=AnnotationResponse, status_code=201)
async def create_annotation(req: AnnotationCreateRequest) -> AnnotationResponse:
    """Create a text annotation (highlight). HTTP 201 on success."""
    now = datetime.now(UTC)
    annotation = AnnotationModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        section_id=req.section_id,
        chunk_id=req.chunk_id,
        selected_text=req.selected_text,
        start_offset=req.start_offset,
        end_offset=req.end_offset,
        color=req.color,
        note_text=req.note_text,
        page_number=req.page_number,
        created_at=now,
    )
    async with get_session_factory()() as session:
        session.add(annotation)
        await session.commit()
        await session.refresh(annotation)
    logger.info("Created annotation %s for doc %s", annotation.id, req.document_id)
    return AnnotationResponse.model_validate(annotation)


@router.get("", response_model=list[AnnotationResponse])
async def list_annotations(document_id: str) -> list[AnnotationResponse]:
    """Return all annotations for a document ordered by created_at asc."""
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(AnnotationModel)
                .where(AnnotationModel.document_id == document_id)
                .order_by(AnnotationModel.created_at)
            )
        ).scalars().all()
    return [AnnotationResponse.model_validate(r) for r in rows]


@router.delete("/{annotation_id}", status_code=204)
async def delete_annotation(annotation_id: str) -> None:
    """Delete an annotation. HTTP 204 on success, 404 if not found."""
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(AnnotationModel).where(AnnotationModel.id == annotation_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        await session.delete(row)
        await session.commit()
    logger.info("Deleted annotation %s", annotation_id)
