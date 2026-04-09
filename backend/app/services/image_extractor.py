"""PDF and EPUB image extraction service.

Pure extraction logic — no DB writes.
Called by image_extract_handler (enrichment job handler).
"""

import hashlib
import logging
import uuid
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image as PILImage

logger = logging.getLogger(__name__)

_MIN_WIDTH = 150
_MIN_HEIGHT = 100
_MAX_DIM = 4000


class ExtractedImage:
    """Value object returned from ImageExtractor; no DB references."""

    def __init__(
        self,
        page: int,
        index: int,
        width: int,
        height: int,
        content_hash: str,
        abs_path: Path,
        rel_path: str,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.page = page
        self.index = index
        self.width = width
        self.height = height
        self.content_hash = content_hash
        self.abs_path = abs_path
        self.rel_path = rel_path


def extract_images_pdf(
    file_path: Path,
    images_dir: Path,
    doc_id: str,
) -> list[ExtractedImage]:
    """Extract images from a PDF file.

    Uses PyMuPDF page.get_images(full=True) + doc.extract_image(xref).
    Normalizes all images to PNG.
    Skips images outside the 150x100 to 4000x4000 bounds.
    Deduplicates via SHA-256 hash within this document.
    Returns list of ExtractedImage value objects (does NOT write to DB).
    """
    out_dir = images_dir / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExtractedImage] = []
    seen_hashes: set[str] = set()

    doc = fitz.open(str(file_path))
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                img_data = doc.extract_image(xref)
            except Exception as exc:
                logger.warning(
                    "PDF image extraction failed xref=%d page=%d: %s", xref, page_idx, exc
                )
                continue

            raw_bytes = img_data["image"]
            content_hash = hashlib.sha256(raw_bytes).hexdigest()
            if content_hash in seen_hashes:
                continue

            try:
                img_pil = PILImage.open(BytesIO(raw_bytes))
                w, h = img_pil.size
            except Exception:
                continue

            if w < _MIN_WIDTH or h < _MIN_HEIGHT:
                continue

            if w > _MAX_DIM or h > _MAX_DIM:
                logger.warning(
                    "Skipping oversized image doc=%s page=%d index=%d size=%dx%d",
                    doc_id,
                    page_idx,
                    img_idx,
                    w,
                    h,
                )
                continue

            rel_path = f"images/{doc_id}/{page_idx}_{img_idx}.png"
            abs_path = out_dir / f"{page_idx}_{img_idx}.png"
            try:
                img_pil.save(str(abs_path), format="PNG")
            except Exception as exc:
                logger.warning("Could not save PNG doc=%s page=%d: %s", doc_id, page_idx, exc)
                continue

            seen_hashes.add(content_hash)
            results.append(
                ExtractedImage(
                    page=page_idx,
                    index=img_idx,
                    width=w,
                    height=h,
                    content_hash=content_hash,
                    abs_path=abs_path,
                    rel_path=rel_path,
                )
            )

    page_count = len(doc)
    doc.close()
    logger.info(
        "PDF image extraction complete doc=%s pages=%d images=%d",
        doc_id,
        page_count,
        len(results),
    )
    return results


def extract_images_epub(
    file_path: Path,
    images_dir: Path,
    doc_id: str,
) -> list[ExtractedImage]:
    """Extract images from an EPUB file.

    Uses ebooklib to iterate EpubImage items.
    Same size/dedup rules as PDF extraction.
    """
    import ebooklib  # noqa: PLC0415
    from ebooklib import epub  # noqa: PLC0415

    out_dir = images_dir / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExtractedImage] = []
    seen_hashes: set[str] = set()

    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})
    except Exception as exc:
        logger.warning("EPUB open failed doc=%s: %s", doc_id, exc)
        return []

    img_idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        raw_bytes = item.get_content()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        if content_hash in seen_hashes:
            continue

        try:
            img_pil = PILImage.open(BytesIO(raw_bytes))
            w, h = img_pil.size
        except Exception:
            continue

        if w < _MIN_WIDTH or h < _MIN_HEIGHT:
            continue

        if w > _MAX_DIM or h > _MAX_DIM:
            logger.warning(
                "Skipping oversized EPUB image doc=%s index=%d size=%dx%d",
                doc_id,
                img_idx,
                w,
                h,
            )
            continue

        rel_path = f"images/{doc_id}/epub_{img_idx}.png"
        abs_path = out_dir / f"epub_{img_idx}.png"
        try:
            img_pil.save(str(abs_path), format="PNG")
        except Exception as exc:
            logger.warning("Could not save EPUB PNG doc=%s: %s", doc_id, exc)
            continue

        seen_hashes.add(content_hash)
        results.append(
            ExtractedImage(
                page=0,  # EPUB has no page numbers
                index=img_idx,
                width=w,
                height=h,
                content_hash=content_hash,
                abs_path=abs_path,
                rel_path=rel_path,
            )
        )
        img_idx += 1

    logger.info("EPUB image extraction complete doc=%s images=%d", doc_id, len(results))
    return results


def extract_images_md(
    images_dir: Path,
    doc_id: str,
) -> list[ExtractedImage]:
    """Scan already-mirrored images for a web article (markdown).

    ArticleExtractor mirrors images to images/{doc_id} during parsing.
    We scan that directory and create ExtractedImage objects for each file.
    """
    out_dir = images_dir / doc_id
    if not out_dir.exists():
        logger.info("MD image extraction: no images found for doc=%s", doc_id)
        return []

    results: list[ExtractedImage] = []
    # ArticleExtractor uses md5 hashes for filenames
    for img_path in out_dir.iterdir():
        if img_path.is_dir() or img_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            continue

        try:
            with PILImage.open(img_path) as img_pil:
                w, h = img_pil.size
                
            # Use file content hash if possible, otherwise filename
            with open(img_path, "rb") as f:
                content_hash = hashlib.sha256(f.read()).hexdigest()

            rel_path = f"images/{doc_id}/{img_path.name}"
            results.append(
                ExtractedImage(
                    page=0,
                    index=len(results),
                    width=w,
                    height=h,
                    content_hash=content_hash,
                    abs_path=img_path,
                    rel_path=rel_path,
                )
            )
        except Exception as exc:
            logger.warning("MD image scanning failed for %s: %s", img_path, exc)

    logger.info("MD image scanning complete doc=%s images=%d", doc_id, len(results))
    return results


async def image_extract_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='image_extract'.

    Called by EnrichmentQueueWorker for each image_extract job.
    Extracts images from the document file, stores ImageModel rows.
    Non-fatal: failures are caught by the worker and set job status='failed'.
    """
    from pathlib import Path as _Path  # noqa: PLC0415

    from sqlalchemy import select as _select  # noqa: PLC0415
    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.config import get_settings  # noqa: PLC0415
    from app.database import get_session_factory  # noqa: PLC0415
    from app.models import ChunkModel, DocumentModel, ImageModel  # noqa: PLC0415

    settings = get_settings()
    images_dir = _Path(settings.DATA_DIR).expanduser() / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    async with get_session_factory()() as session:
        doc_result = await session.execute(
            _select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        existing_hashes_result = await session.execute(
            _select(ImageModel.content_hash).where(ImageModel.document_id == document_id)
        )
        existing_hashes: set[str] = {row[0] for row in existing_hashes_result.all()}

        chunks_result = await session.execute(
            _select(ChunkModel.id, ChunkModel.page_number)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.page_number, ChunkModel.chunk_index)
        )
        chunks = chunks_result.all()

    fmt = doc.format.lower()
    file_path = _Path(doc.file_path)

    if fmt == "pdf":
        extracted = extract_images_pdf(file_path, images_dir, document_id)
    elif fmt == "epub":
        extracted = extract_images_epub(file_path, images_dir, document_id)
    elif fmt in ("md", "markdown"):
        extracted = extract_images_md(images_dir, document_id)
    else:
        logger.info("image_extract_handler: format %s has no image extraction", fmt)
        return

    def _find_nearest_chunk(page: int) -> str | None:
        best_id: str | None = None
        for chunk_id, chunk_page in chunks:
            if chunk_page <= page:
                best_id = chunk_id
            else:
                break
        return best_id

    new_images: list[ImageModel] = []
    for img in extracted:
        if img.content_hash in existing_hashes:
            continue
        existing_hashes.add(img.content_hash)
        nearest_chunk = _find_nearest_chunk(img.page)
        new_images.append(
            ImageModel(
                id=img.id,
                document_id=document_id,
                chunk_id=nearest_chunk,
                page=img.page,
                path=img.rel_path,
                width=img.width,
                height=img.height,
                content_hash=img.content_hash,
            )
        )

    if new_images:
        async with get_session_factory()() as session:
            session.add_all(new_images)
            await session.commit()

        # Enqueue image_analyze job for vision LLM analysis (S134)
        import uuid as _uuid  # noqa: PLC0415

        from app.models import EnrichmentJobModel  # noqa: PLC0415

        analyze_job_id = str(_uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                EnrichmentJobModel(
                    id=analyze_job_id,
                    document_id=document_id,
                    job_type="image_analyze",
                    status="pending",
                )
            )
            await session.commit()
        logger.info(
            "image_extract_handler: enqueued image_analyze job=%s doc=%s",
            analyze_job_id,
            document_id,
        )

    async with get_session_factory()() as session:
        await session.execute(
            _update(DocumentModel)
            .where(
                DocumentModel.id == document_id,
                DocumentModel.stage == "enriching",
            )
            .values(stage="complete")
        )
        await session.commit()

    logger.info(
        "image_extract_handler: done doc=%s new_images=%d",
        document_id,
        len(new_images),
    )
