"""POST /annotations, GET /annotations, DELETE /annotations/{id}.

Persistent text highlights anchored to document sections. No document
validation on write -- annotation storage is decoupled from document
lifecycle to keep the router simple.

Persistence is delegated to `AnnotationRepo`.
"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.repos.annotation_repo import AnnotationRepo, get_annotation_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/annotations", tags=["annotations"])


class AnnotationCreateRequest(BaseModel):
    document_id: str
    section_id: str
    chunk_id: str | None = None
    selected_text: str
    start_offset: int = 0
    end_offset: int = 0
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
async def create_annotation(
    req: AnnotationCreateRequest,
    repo: AnnotationRepo = Depends(get_annotation_repo),
) -> AnnotationResponse:
    """Create a text annotation (highlight). HTTP 201 on success."""
    annotation = await repo.create(
        document_id=req.document_id,
        section_id=req.section_id,
        chunk_id=req.chunk_id,
        selected_text=req.selected_text,
        start_offset=req.start_offset,
        end_offset=req.end_offset,
        color=req.color,
        note_text=req.note_text,
        page_number=req.page_number,
    )
    logger.info("Created annotation %s for doc %s", annotation.id, req.document_id)
    return AnnotationResponse.model_validate(annotation)


@router.get("", response_model=list[AnnotationResponse])
async def list_annotations(
    document_id: str,
    repo: AnnotationRepo = Depends(get_annotation_repo),
) -> list[AnnotationResponse]:
    """Return all annotations for a document ordered by created_at asc."""
    rows = await repo.list_for_document(document_id)
    return [AnnotationResponse.model_validate(r) for r in rows]


@router.delete("/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: str,
    repo: AnnotationRepo = Depends(get_annotation_repo),
) -> None:
    """Delete an annotation. HTTP 204 on success, 404 if not found."""
    await repo.delete(annotation_id)
    logger.info("Deleted annotation %s", annotation_id)
