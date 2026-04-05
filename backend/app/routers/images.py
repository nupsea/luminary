"""Images API router — S133.

Endpoints:
  GET /documents/{id}/images       -- paginated image list for a document
  GET /images/{id}/raw             -- serve raw PNG file
  GET /documents/{id}/enrichment   -- enrichment job list for a document
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import DocumentModel, EnrichmentJobModel, ImageModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["images"])


class ImageItem(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None
    page: int
    path: str
    width: int
    height: int
    content_hash: str
    image_type: str | None
    description: str | None
    created_at: str


class ImageListResponse(BaseModel):
    items: list[ImageItem]
    total: int
    page: int
    page_size: int


class EnrichmentJobItem(BaseModel):
    id: str
    document_id: str
    job_type: str
    status: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    created_at: str


@router.get("/documents/{document_id}/images", response_model=ImageListResponse)
async def get_document_images(
    document_id: str,
    page: int = 1,
    page_size: int = 20,
) -> ImageListResponse:
    """Return paginated image list for a document.

    Returns empty list (not 404) for text-only documents.
    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        doc_check = await session.execute(
            select(DocumentModel.id).where(DocumentModel.id == document_id)
        )
        if doc_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Document not found")

        result = await session.execute(
            select(ImageModel)
            .where(ImageModel.document_id == document_id)
            .order_by(ImageModel.page, ImageModel.created_at)
        )
        all_images = result.scalars().all()

    total = len(all_images)
    start = (page - 1) * page_size
    page_images = all_images[start : start + page_size]
    return ImageListResponse(
        items=[
            ImageItem(
                id=img.id,
                document_id=img.document_id,
                chunk_id=img.chunk_id,
                page=img.page,
                path=img.path,
                width=img.width,
                height=img.height,
                content_hash=img.content_hash,
                image_type=img.image_type,
                description=img.description,
                created_at=img.created_at.isoformat(),
            )
            for img in page_images
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/images/{image_id}/raw")
async def serve_image_raw(image_id: str) -> FileResponse:
    """Serve the raw PNG file for an extracted image.

    Returns 200 with Content-Type image/png.
    Returns 404 if image not found in DB or file missing from disk.
    """
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ImageModel).where(ImageModel.id == image_id)
        )
        img = result.scalar_one_or_none()

    if img is None:
        raise HTTPException(status_code=404, detail="Image not found")

    settings = get_settings()
    abs_path = Path(settings.DATA_DIR).expanduser() / img.path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    return FileResponse(str(abs_path), media_type="image/png")


@router.get("/images/local/{doc_id}/{filename}")
async def serve_local_article_image(doc_id: str, filename: str) -> FileResponse:
    """Serve a locally mirrored image for an article."""
    settings = get_settings()
    abs_path = Path(settings.DATA_DIR).expanduser() / "images" / doc_id / filename
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Local image not found")

    # Detect media type from extension
    ext = filename.rsplit(".", maxsplit=1)[-1].lower()
    media_type = (
        f"image/{ext}"
        if ext in ["png", "jpg", "jpeg", "gif", "webp", "svg"]
        else "image/png"
    )
    return FileResponse(str(abs_path), media_type=media_type)


@router.get("/documents/{document_id}/enrichment", response_model=list[EnrichmentJobItem])
async def get_enrichment_jobs(document_id: str) -> list[EnrichmentJobItem]:
    """Return all enrichment jobs for a document (all job_types and statuses).

    Returns 404 if document does not exist.
    Returns [] if no enrichment jobs have been created yet.
    """
    async with get_session_factory()() as session:
        doc_check = await session.execute(
            select(DocumentModel.id).where(DocumentModel.id == document_id)
        )
        if doc_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Document not found")

        result = await session.execute(
            select(EnrichmentJobModel)
            .where(EnrichmentJobModel.document_id == document_id)
            .order_by(EnrichmentJobModel.created_at)
        )
        jobs = result.scalars().all()

    return [
        EnrichmentJobItem(
            id=j.id,
            document_id=j.document_id,
            job_type=j.job_type,
            status=j.status,
            started_at=j.started_at.isoformat() if j.started_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            error_message=j.error_message,
            created_at=j.created_at.isoformat(),
        )
        for j in jobs
    ]
