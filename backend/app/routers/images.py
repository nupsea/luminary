"""Images API router — .

Endpoints:
  GET  /documents/{id}/images            -- paginated image list for a document
  GET  /images/{id}/raw                  -- serve raw PNG file
  POST /documents/{id}/images/reextract  -- re-run image extraction for a document
  GET  /documents/{id}/enrichment        -- enrichment job list for a document
  GET  /enrichment/queue                 -- library-wide enrichment backlog
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_session_factory
from app.exceptions import InvalidInput, LuminaryError, NotFound
from app.models import DocumentModel, ImageModel
from app.repos._helpers import get_or_404
from app.repos.enrichment_repo import EnrichmentRepo
from app.runtime.asset_response import UNTRUSTED_ASSET_HEADERS
from app.runtime.request_auth import device_scope
from app.storage import library_root

logger = logging.getLogger(__name__)
router = APIRouter(tags=["images"])


class ImageItem(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None
    section_id: str | None = None
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


class ReextractResponse(BaseModel):
    job_id: str
    queued: bool


class EnrichmentJobItem(BaseModel):
    id: str
    document_id: str
    job_type: str
    status: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    created_at: str


class UploadResponse(BaseModel):
    path: str
    filename: str


class EnrichmentQueueSummary(BaseModel):
    pending: int
    running: int
    skipped: int
    failed: int
    documents_active: int
    active: bool


# What a note may hold. Anything else could be served back as a document on the app's origin.
_NOTE_IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg"}
)
_SCENE_SUFFIX = ".excalidraw.json"


def _note_asset_extension(filename: str, mime: str) -> str:
    if filename.endswith(_SCENE_SUFFIX) and mime in {"application/json", "text/json"}:
        return _SCENE_SUFFIX
    if not mime.startswith("image/"):
        raise InvalidInput("Only image files or Excalidraw JSON scenes are allowed")
    ext = Path(filename).suffix.lower()
    if not ext:
        # A pasted clipboard image arrives as "blob": name it from its type.
        subtype = mime.rsplit("/", maxsplit=1)[-1].split("+", maxsplit=1)[0].lower()
        ext = ".jpg" if subtype == "jpeg" else f".{subtype}"
        return ext if ext in _NOTE_IMAGE_EXTENSIONS else ".png"
    if ext not in _NOTE_IMAGE_EXTENSIONS:
        raise InvalidInput(f"A note cannot hold a {ext} file; use an image.")
    return ext


@router.post(
    "/images/notes", response_model=UploadResponse, dependencies=[device_scope("notes:write")]
)
async def upload_note_image(file: UploadFile = File(...)) -> UploadResponse:
    """Upload a note asset such as an image, SVG diagram, or Excalidraw scene.

    Saves to DATA_DIR/images/notes/{uuid}_{filename}.
    Returns the __LUMINARY_IMG__ prefixed path for Markdown resolution.
    """
    settings = get_settings()
    data_dir = library_root(settings)
    notes_img_dir = data_dir / "images" / "notes"
    notes_img_dir.mkdir(parents=True, exist_ok=True)

    mime = file.content_type or ""
    filename = file.filename or "asset"
    ext = _note_asset_extension(filename, mime)
    is_excalidraw_scene = ext == _SCENE_SUFFIX
    unique_filename = f"{uuid.uuid4()}{ext}"
    target_path = notes_img_dir / unique_filename

    try:
        content = await file.read()
        if is_excalidraw_scene:
            try:
                scene = json.loads(content)
            except json.JSONDecodeError as exc:
                raise InvalidInput("Invalid Excalidraw JSON scene") from exc
            if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
                raise InvalidInput("Invalid Excalidraw JSON scene")  # noqa: TRY301
        await asyncio.to_thread(target_path.write_bytes, content)
    except LuminaryError:
        raise
    except Exception as exc:
        logger.exception("Failed to save note image")
        raise LuminaryError("Failed to save image file") from exc

    # Returns the pseudo-path that MarkdownRenderer.tsx resolves to API_BASE
    return UploadResponse(
        path=f"__LUMINARY_IMG__/notes/{unique_filename}",
        filename=unique_filename,
    )


@router.get(
    "/documents/{document_id}/images",
    response_model=ImageListResponse,
    dependencies=[device_scope("read")],
)
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
        await get_or_404(session, DocumentModel, document_id, name="Document")

        all_rows = await EnrichmentRepo(session).images_with_sections(document_id)

    total = len(all_rows)
    start = (page - 1) * page_size
    page_rows = all_rows[start : start + page_size]
    return ImageListResponse(
        items=[
            ImageItem(
                id=img.id,
                document_id=img.document_id,
                chunk_id=img.chunk_id,
                section_id=sec_id,
                page=img.page,
                path=img.path,
                width=img.width,
                height=img.height,
                content_hash=img.content_hash,
                image_type=img.image_type,
                description=img.description,
                created_at=img.created_at.isoformat(),
            )
            for img, sec_id in page_rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/images/{image_id}/raw", dependencies=[device_scope("read")])
async def serve_image_raw(image_id: str) -> FileResponse:
    """Serve the raw PNG file for an extracted image.

    Returns 200 with Content-Type image/png.
    Returns 404 if image not found in DB or file missing from disk.
    """
    async with get_session_factory()() as session:
        img = await get_or_404(session, ImageModel, image_id, name="Image")

    settings = get_settings()
    abs_path = library_root(settings) / img.path
    if not abs_path.exists():
        raise NotFound("Image file not found on disk")

    return FileResponse(str(abs_path), media_type="image/png", headers=UNTRUSTED_ASSET_HEADERS)


@router.get("/images/local/{doc_id}/{filename}", dependencies=[device_scope("read")])
async def serve_local_article_image(doc_id: str, filename: str) -> FileResponse:
    """Serve a locally mirrored image for an article."""
    settings = get_settings()
    # doc_id and filename are unvalidated path segments. Starlette's [^/]+ match
    # stops a literal slash but not "..", and percent-encoded "%2e%2e" survives
    # ASGI decoding -- without containment this served anything one level above
    # images/, which is DATA_DIR itself (luminary.db included).
    root = (library_root(settings) / "images").resolve()
    abs_path = (root / doc_id / filename).resolve()
    if not abs_path.is_relative_to(root) or not abs_path.is_file():
        raise NotFound("Local image not found")

    # Detect media type from extension
    ext = filename.rsplit(".", maxsplit=1)[-1].lower()
    if ext == "svg":
        media_type = "image/svg+xml"
    elif ext == "json":
        media_type = "application/json"
    elif ext in ["tiff", "tif"]:
        media_type = "image/tiff"
    else:
        common_types = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
        media_type = f"image/{ext}" if ext in common_types else "image/png"
    return FileResponse(str(abs_path), media_type=media_type, headers=UNTRUSTED_ASSET_HEADERS)


@router.post("/documents/{document_id}/images/reextract", response_model=ReextractResponse)
async def reextract_document_images(document_id: str) -> ReextractResponse:
    """Queue a fresh image_extract job for a document.

    Extraction dedupes on content hash, so this only adds figures the previous run
    missed — the way an already-ingested document picks up an extraction improvement
    without being re-uploaded. Returns the existing job when one is already queued.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        jobs = EnrichmentRepo(session)
        existing = await jobs.active_job(document_id, "image_extract")
        if existing is not None:
            return ReextractResponse(job_id=existing.id, queued=False)

        # Drop any pending image_analyze for this document. Its input set is
        # exactly what this re-extraction is about to change, and the worker
        # runs a document's jobs sequentially -- so left queued, the analyze
        # job runs FIRST and the re-extract waits behind it. On the case this
        # exists for, that is the wrong way round by hours: 77 stale full-page
        # rasters were queued for a vision call each, and the re-extract that
        # would have retired them sat behind all 77. The handler enqueues a
        # fresh analyze job for whatever survives.
        superseded = await jobs.supersede_pending(
            document_id,
            "image_analyze",
            "Superseded by a re-extraction; a fresh analyze job "
            "covers the images that survived it.",
        )
        job = jobs.enqueue(document_id, "image_extract")
        await session.commit()

    if superseded:
        logger.info(
            "reextract_document_images: superseded %d pending image_analyze job(s) doc=%s",
            len(superseded),
            document_id,
        )

    logger.info("reextract_document_images: queued job=%s doc=%s", job.id, document_id)
    return ReextractResponse(job_id=job.id, queued=True)


@router.get("/enrichment/queue", response_model=EnrichmentQueueSummary)
async def get_enrichment_queue() -> EnrichmentQueueSummary:
    """Library-wide enrichment backlog, so background model work is visible.

    Installing a component re-queues every job that was skipped for want of it,
    which can be minutes of vision inference per document with nothing in the
    UI to say so.
    """
    async with get_session_factory()() as session:
        by_status = await EnrichmentRepo(session).queue_counts()
    pending, pending_docs = by_status.get("pending", (0, 0))
    running, running_docs = by_status.get("running", (0, 0))
    return EnrichmentQueueSummary(
        pending=pending,
        running=running,
        skipped=by_status.get("skipped", (0, 0))[0],
        failed=by_status.get("failed", (0, 0))[0],
        documents_active=max(pending_docs, running_docs),
        active=bool(pending or running),
    )


@router.get("/documents/{document_id}/enrichment", response_model=list[EnrichmentJobItem])
async def get_enrichment_jobs(document_id: str) -> list[EnrichmentJobItem]:
    """Return all enrichment jobs for a document (all job_types and statuses).

    Returns 404 if document does not exist.
    Returns [] if no enrichment jobs have been created yet.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        jobs = await EnrichmentRepo(session).jobs_for_document(document_id)

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
