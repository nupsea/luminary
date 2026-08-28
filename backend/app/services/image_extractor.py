"""PDF and EPUB image extraction service.

The extract_images_* functions are pure — they read a file and write PNGs, never
the DB. Only image_extract_handler (the enrichment job handler) touches SQLite.
"""

import asyncio
import hashlib
import logging
import uuid
from collections import deque
from io import BytesIO
from pathlib import Path

import ebooklib
import fitz  # PyMuPDF
from ebooklib import epub
from PIL import Image as PILImage
from sqlalchemy import delete as _delete
from sqlalchemy import func, select
from sqlalchemy import text as _text
from sqlalchemy import update as _update

from app import config as _config_module  # indirect: get_settings is patched
from app import database as _database_module  # indirect: get_session_factory is patched
from app.models import ChunkModel, DocumentModel, EnrichmentJobModel, ImageModel
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)

logger = logging.getLogger(__name__)

_MIN_WIDTH = 150
_MIN_HEIGHT = 100
_MAX_DIM = 4000

# Vector-figure fallback tuning, in PDF points (1/72 inch) unless noted.
_CLUSTER_CELL_PT = 6.0  # occupancy-grid resolution
_CLUSTER_GAP_PT = 9.0  # primitives within this distance belong to one figure
_CLIP_PAD_PT = 12.0  # captured around the cluster so edge labels survive
_MIN_FIGURE_PT = 60.0  # smaller regions are rules, bullets and highlight boxes
_MIN_FIGURE_PRIMITIVES = 3
# A region covering nearly the whole page is a page frame or background wash.
_MAX_FIGURE_PAGE_FRACTION = 0.85
# How far past the page box a drawing primitive may extend before it is read as
# a flowed-column container rather than ink. Ink is bounded by the page it is
# drawn on; a background rectangle inherited from a reflowable source is bounded
# by the *flow*, so it arrives hundreds of points tall on a 792pt page.
#
# Bracketed by two measured cases from SQL_Cookbook_2006 (128pp, PDF from an
# EPUB-style flow): the largest primitive that is genuinely on a page measures
# 0.938x the page box, and the smallest column container measures 1.20x --
# the rest of that population runs to 42.21x, a median of 29.78x. 1.05 sits in
# that gap with room on both sides, and the margin above 1.0 is for a figure
# that bleeds a few points past the trim.
_MAX_PRIMITIVE_PAGE_SPAN = 1.05
# Prose detection, bracketed by measurement in _is_prose_block. A text line
# spanning more than _PROSE_LINE_WIDTH_FRACTION of a region's width is a
# full-width line; when more than _MAX_PROSE_LINE_SHARE of a region's lines are
# full-width, the region is a paragraph someone drew a border around. The gap
# measured across five documents is 0.176 (widest real figure) to 0.333
# (narrowest prose block).
_PROSE_LINE_WIDTH_FRACTION = 0.6
_MAX_PROSE_LINE_SHARE = 0.25
# Fewer lines than a paragraph has: refuse to judge rather than guess.
_MIN_PROSE_LINES = 3
_VECTOR_RENDER_DPI = 150
# One color covering this much of a render means an empty framed box. Sparse
# line-art figures measure well below it, so real diagrams survive.
_BLANK_DOMINANT_FRACTION = 0.99
_MAX_VECTOR_FIGURES_PER_PAGE = 4
# Runaway guard only; every recovered figure costs a vision LLM call downstream.
_MAX_VECTOR_FIGURES_PER_DOC = 300


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


def _exceeds_page_box(raw_rect, page_rect) -> bool:
    """True when a drawing primitive is larger than the page it sits on.

    Such a primitive is not a drawing of anything. It is the background of a
    reflowed text column: PDFs generated from EPUB-style flowable sources emit
    one fill rectangle spanning the whole flow, which is then clipped to each
    page as it is laid out.

    The measurement has to happen on the UNCLIPPED rectangle. Clipped, a
    21,608pt-tall column background on a 792pt page becomes exactly the page's
    text column -- 0.765 of the page area, comfortably under
    _MAX_FIGURE_PAGE_FRACTION -- so the wash guard passes it, it paints the
    whole column onto the occupancy grid, and every page of prose in the book
    is recovered as a "figure". SQL_Cookbook_2006 yielded 81 images that way,
    79 of them full pages of body text, each costing a vision LLM call to
    describe text that ingestion had already chunked and indexed verbatim.
    """
    if page_rect.width <= 0 or page_rect.height <= 0:
        return False
    return (
        raw_rect.width > _MAX_PRIMITIVE_PAGE_SPAN * page_rect.width
        or raw_rect.height > _MAX_PRIMITIVE_PAGE_SPAN * page_rect.height
    )


def _is_prose_block(page, bbox) -> bool:
    """True when a candidate region is a bordered paragraph, not a figure.

    The second half of the reflowed-source problem. `_exceeds_page_box` removes
    the column container; what survives it are the ruled boxes a book draws
    around admonitions -- TIP/NOTE callouts, title-page panels, code washes.
    Those are three primitives around a paragraph, so every geometric test
    passes them, and the vision model duly reports "the image displays a section
    of text" for a paragraph ingestion already chunked, embedded and indexed
    verbatim. That description is a lossy paraphrase of text already indexed, so
    the call costs minutes to make image search slightly worse.

    The signal is line *shape*, not how much text there is. A paragraph's lines
    span the box that contains them; a diagram's labels annotate geometry and do
    not. Density fails here and was tried first: ResNet's Figure 2 -- the
    residual block, four labels in 102x96pt -- is 0.212 text by area, denser
    than three of the four SQL Cookbook callouts, and a coverage threshold drops
    it. Line-span separates the same two populations cleanly.

    Measured over 96 candidate regions from five documents (SQL_Cookbook_2006
    and the arXiv PDFs for Attention/BERT/ResNet/Adam), as the share of a
    region's text lines that span more than _PROSE_LINE_WIDTH_FRACTION of its
    width:

        ResNet Fig 2, residual block          0.143  <- keep
        Adam Fig 3, widest real figure        0.176  <- keep  (the ceiling)
        ...
        SQL Cookbook title panel, 3 lines     0.333  <- drop  (the floor)
        NOTE callouts, pages 7 / 40 / 91      0.778
        title panel, page 1                   1.000

    _MAX_PROSE_LINE_SHARE sits in that 0.176-0.333 gap. The floor of the prose
    population is a three-line panel, which is why _MIN_PROSE_LINES refuses to
    judge anything shorter: below three lines there is no paragraph shape to
    read, and a figure carrying one wide caption line would otherwise score 1.0.
    """
    lines: list[float] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 0 = text; 1 = image
            continue
        for line in block["lines"]:
            if not "".join(span["text"] for span in line["spans"]).strip():
                continue
            rect = fitz.Rect(line["bbox"])
            centre = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            if bbox.contains(centre):
                lines.append((rect.x1 - rect.x0) / bbox.width)

    if len(lines) < _MIN_PROSE_LINES:
        return False
    full_width = sum(1 for width in lines if width > _PROSE_LINE_WIDTH_FRACTION)
    return (full_width / len(lines)) > _MAX_PROSE_LINE_SHARE


def _cluster_drawings(page) -> list:
    """Group a page's vector drawing primitives into candidate figure regions.

    Primitive bounding boxes are painted onto a coarse occupancy grid, inflated by
    _CLUSTER_GAP_PT so the hundreds of short strokes making up one plot join into a
    single blob, then connected components are read back as rectangles.

    Returns fitz.Rect regions, largest first, already filtered to plausible figures.
    """
    page_rect = page.rect
    if page_rect.width <= 0 or page_rect.height <= 0:
        return []

    page_area = page_rect.width * page_rect.height
    rects = []
    for drawing in page.get_drawings():
        raw_rect = drawing.get("rect")
        if raw_rect is None:
            continue
        raw = fitz.Rect(raw_rect)
        # A container from a reflowed source, measured BEFORE clipping. Ink is
        # bounded by the page it is drawn on; a column background inherited from
        # an EPUB-style flow is not, and clipping is what hides it -- see
        # _exceeds_page_box.
        if _exceeds_page_box(raw, page_rect):
            continue
        rect = raw & page_rect
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue
        # A background wash or page border spans the grid and would bridge every
        # figure on the page into one component, which the same fraction check
        # then discards -- losing the real figures with it.
        if rect.get_area() > _MAX_FIGURE_PAGE_FRACTION * page_area:
            continue
        rects.append(rect)
    if not rects:
        return []

    cols = int(page_rect.width / _CLUSTER_CELL_PT) + 1
    rows = int(page_rect.height / _CLUSTER_CELL_PT) + 1
    occupied = bytearray(cols * rows)
    for rect in rects:
        x0 = max(0, int((rect.x0 - page_rect.x0 - _CLUSTER_GAP_PT) / _CLUSTER_CELL_PT))
        x1 = min(cols - 1, int((rect.x1 - page_rect.x0 + _CLUSTER_GAP_PT) / _CLUSTER_CELL_PT))
        y0 = max(0, int((rect.y0 - page_rect.y0 - _CLUSTER_GAP_PT) / _CLUSTER_CELL_PT))
        y1 = min(rows - 1, int((rect.y1 - page_rect.y0 + _CLUSTER_GAP_PT) / _CLUSTER_CELL_PT))
        for cell_y in range(y0, y1 + 1):
            row_base = cell_y * cols
            for cell_x in range(x0, x1 + 1):
                occupied[row_base + cell_x] = 1

    visited = bytearray(cols * rows)
    figures: list = []
    for seed in range(cols * rows):
        if not occupied[seed] or visited[seed]:
            continue
        visited[seed] = 1
        queue = deque([seed])
        min_x = max_x = seed % cols
        min_y = max_y = seed // cols
        while queue:
            cell = queue.popleft()
            cell_y, cell_x = divmod(cell, cols)
            min_x, max_x = min(min_x, cell_x), max(max_x, cell_x)
            min_y, max_y = min(min_y, cell_y), max(max_y, cell_y)
            for delta_y, delta_x in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                next_y, next_x = cell_y + delta_y, cell_x + delta_x
                if 0 <= next_y < rows and 0 <= next_x < cols:
                    neighbour = next_y * cols + next_x
                    if occupied[neighbour] and not visited[neighbour]:
                        visited[neighbour] = 1
                        queue.append(neighbour)

        bbox = fitz.Rect(
            page_rect.x0 + min_x * _CLUSTER_CELL_PT,
            page_rect.y0 + min_y * _CLUSTER_CELL_PT,
            page_rect.x0 + (max_x + 1) * _CLUSTER_CELL_PT,
            page_rect.y0 + (max_y + 1) * _CLUSTER_CELL_PT,
        ) & page_rect
        if bbox.width < _MIN_FIGURE_PT or bbox.height < _MIN_FIGURE_PT:
            continue
        if bbox.get_area() > _MAX_FIGURE_PAGE_FRACTION * page_area:
            continue
        primitives = sum(
            1
            for rect in rects
            if bbox.contains(fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2))
        )
        if primitives < _MIN_FIGURE_PRIMITIVES:
            continue
        if _is_prose_block(page, bbox):
            continue
        figures.append(bbox)

    figures.sort(key=lambda r: r.get_area(), reverse=True)
    return figures[:_MAX_VECTOR_FIGURES_PER_PAGE]


def _is_blank_render(img_pil: PILImage.Image) -> bool:
    """True when a rasterized clip carries no ink worth analyzing.

    Guard for the vector path only: clustering can fence off an empty framed box,
    and a blank PNG would otherwise cost a vision LLM call. Mirrors the near-blank
    rule the enricher applies to already-stored images, so nothing reaches the DB
    that would be classified 'decorative' a step later.
    """
    try:
        colors = img_pil.convert("RGB").getcolors(maxcolors=1 << 16)
    except Exception:
        return False
    if colors is None:
        return False
    total = sum(count for count, _ in colors)
    if total == 0:
        return True
    return max(count for count, _ in colors) / total > _BLANK_DOMINANT_FRACTION


def _store_png(
    img_pil: PILImage.Image,
    content_hash: str,
    seen_hashes: set[str],
    out_dir: Path,
    doc_id: str,
    page_idx: int,
    index: int,
    filename: str,
) -> ExtractedImage | None:
    """Apply the shared size/dedup rules and write the PNG. None when rejected."""
    if content_hash in seen_hashes:
        return None

    try:
        w, h = img_pil.size
    except Exception:
        return None

    if w < _MIN_WIDTH or h < _MIN_HEIGHT:
        return None

    if w > _MAX_DIM or h > _MAX_DIM:
        logger.warning(
            "Skipping oversized image doc=%s page=%d index=%d size=%dx%d",
            doc_id,
            page_idx,
            index,
            w,
            h,
        )
        return None

    abs_path = out_dir / filename
    try:
        img_pil.save(str(abs_path), format="PNG")
    except Exception as exc:
        logger.warning("Could not save PNG doc=%s page=%d: %s", doc_id, page_idx, exc)
        return None

    seen_hashes.add(content_hash)
    return ExtractedImage(
        page=page_idx,
        index=index,
        width=w,
        height=h,
        content_hash=content_hash,
        abs_path=abs_path,
        rel_path=f"images/{doc_id}/{filename}",
    )


def _extract_vector_figures_page(
    page,
    page_idx: int,
    out_dir: Path,
    doc_id: str,
    seen_hashes: set[str],
    limit: int,
) -> list[ExtractedImage]:
    """Rasterize up to `limit` of the vector-drawn figures on one page."""
    results: list[ExtractedImage] = []
    for fig_idx, bbox in enumerate(_cluster_drawings(page)):
        if len(results) >= limit:
            break
        # Drawing bounds exclude text, so axis labels and captions sitting just
        # outside the strokes are only captured by padding the clip.
        clip = fitz.Rect(
            bbox.x0 - _CLIP_PAD_PT,
            bbox.y0 - _CLIP_PAD_PT,
            bbox.x1 + _CLIP_PAD_PT,
            bbox.y1 + _CLIP_PAD_PT,
        ) & page.rect
        try:
            raw_bytes = page.get_pixmap(clip=clip, dpi=_VECTOR_RENDER_DPI).tobytes("png")
            img_pil = PILImage.open(BytesIO(raw_bytes))
            img_pil.load()
        except Exception as exc:
            logger.warning(
                "Vector figure render failed doc=%s page=%d index=%d: %s",
                doc_id,
                page_idx,
                fig_idx,
                exc,
            )
            continue

        if _is_blank_render(img_pil):
            continue

        stored = _store_png(
            img_pil,
            hashlib.sha256(raw_bytes).hexdigest(),
            seen_hashes,
            out_dir,
            doc_id,
            page_idx,
            fig_idx,
            f"{page_idx}_v{fig_idx}.png",
        )
        if stored is not None:
            results.append(stored)
    return results


def extract_images_pdf(
    file_path: Path,
    images_dir: Path,
    doc_id: str,
    vector_fallback: bool = True,
) -> list[ExtractedImage]:
    """Extract images from a PDF file.

    Uses PyMuPDF page.get_images(full=True) + doc.extract_image(xref).
    Normalizes all images to PNG.
    Skips images outside the 150x100 to 4000x4000 bounds.
    Deduplicates via SHA-256 hash within this document.
    Returns list of ExtractedImage value objects (does NOT write to DB).

    When a page yields no raster image and vector_fallback is on, its vector
    drawings are clustered into figure regions and rasterized instead — without
    this, a LaTeX-authored paper extracts zero images however many figures it has.
    """
    out_dir = images_dir / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExtractedImage] = []
    seen_hashes: set[str] = set()
    vector_count = 0

    doc = fitz.open(str(file_path))
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        image_list = page.get_images(full=True)
        page_results = 0
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
            try:
                img_pil = PILImage.open(BytesIO(raw_bytes))
            except Exception:
                logger.debug("undecodable embedded image, skipped", exc_info=True)
                continue

            stored = _store_png(
                img_pil,
                hashlib.sha256(raw_bytes).hexdigest(),
                seen_hashes,
                out_dir,
                doc_id,
                page_idx,
                img_idx,
                f"{page_idx}_{img_idx}.png",
            )
            if stored is not None:
                results.append(stored)
                page_results += 1

        if page_results or not vector_fallback:
            continue
        budget = min(_MAX_VECTOR_FIGURES_PER_PAGE, _MAX_VECTOR_FIGURES_PER_DOC - vector_count)
        if budget <= 0:
            continue
        try:
            figures = _extract_vector_figures_page(
                page, page_idx, out_dir, doc_id, seen_hashes, budget
            )
        except Exception as exc:
            logger.warning(
                "Vector figure detection failed doc=%s page=%d: %s", doc_id, page_idx, exc
            )
            continue
        vector_count += len(figures)
        results.extend(figures)

    page_count = len(doc)
    doc.close()
    logger.info(
        "PDF image extraction complete doc=%s pages=%d images=%d (vector figures=%d)",
        doc_id,
        page_count,
        len(results),
        vector_count,
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
        try:
            img_pil = PILImage.open(BytesIO(raw_bytes))
        except Exception:
            logger.debug("undecodable EPUB image, skipped", exc_info=True)
            continue

        stored = _store_png(
            img_pil,
            hashlib.sha256(raw_bytes).hexdigest(),
            seen_hashes,
            out_dir,
            doc_id,
            0,  # EPUB has no page numbers
            img_idx,
            f"epub_{img_idx}.png",
        )
        if stored is not None:
            results.append(stored)
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
        allowed = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        if img_path.is_dir() or img_path.suffix.lower() not in allowed:
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


async def _record_job_note(job_id: str, note: str) -> None:
    """Attach a diagnostic note to the job row.

    The worker overwrites status but not error_message, so a degraded-but-finished
    job keeps its explanation while still reporting 'done'. A note on a 'done' job
    is therefore an explanation, not a failure -- readers must check status too.
    """
    try:
        async with _database_module.get_session_factory()() as session:
            await session.execute(
                _update(EnrichmentJobModel)
                .where(EnrichmentJobModel.id == job_id)
                .values(error_message=note)
            )
            await session.commit()
    except Exception as exc:
        logger.warning("image_extract_handler: could not record job note job=%s: %s", job_id, exc)


async def image_extract_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='image_extract'.

    Called by EnrichmentQueueWorker for each image_extract job.
    Extracts images from the document file, stores ImageModel rows.
    Non-fatal: failures are caught by the worker and set job status='failed'.
    """



    settings = _config_module.get_settings()
    images_dir = Path(settings.DATA_DIR).expanduser() / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    async with _database_module.get_session_factory()() as session:
        doc_result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        existing_hashes_result = await session.execute(
            select(ImageModel.content_hash).where(ImageModel.document_id == document_id)
        )
        existing_hashes: set[str] = {row[0] for row in existing_hashes_result.all()}

        chunks_result = await session.execute(
            select(ChunkModel.id, ChunkModel.page_number)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.page_number, ChunkModel.chunk_index)
        )
        chunks = chunks_result.all()

    fmt = doc.format.lower()
    file_path = Path(doc.file_path)

    if fmt not in ("pdf", "epub", "md", "markdown"):
        logger.info("image_extract_handler: format %s has no image extraction", fmt)
        return

    # Best-effort: an unreadable PDF still leaves the rest of the document usable,
    # so degrade to "no images" with a recorded cause rather than failing the job.
    # Off-loop because rasterizing a large PDF is seconds of CPU on the single
    # server loop the worker shares with every live request.
    note: str | None = None
    try:
        if fmt == "pdf":
            extracted = await asyncio.to_thread(
                extract_images_pdf,
                file_path,
                images_dir,
                document_id,
                settings.PDF_VECTOR_FIGURES,
            )
        elif fmt == "epub":
            extracted = await asyncio.to_thread(
                extract_images_epub, file_path, images_dir, document_id
            )
        else:
            extracted = extract_images_md(images_dir, document_id)
    except Exception as exc:
        extracted = []
        note = (
            f"Image extraction failed ({type(exc).__name__}: {exc}); "
            "document indexed without images."
        )
        logger.warning(
            "image_extract_handler: extraction failed doc=%s format=%s -- %s",
            document_id,
            fmt,
            exc,
            exc_info=exc,
        )

    if note is None and not extracted and not existing_hashes:
        note = "No images found in this document."
        logger.warning(
            "image_extract_handler: no images extracted doc=%s format=%s", document_id, fmt
        )

    if note is not None:
        await _record_job_note(job_id, note)

    def _find_nearest_chunk(page: int) -> str | None:
        best_id: str | None = None
        for chunk_id, chunk_page in chunks:
            if chunk_page <= page:
                best_id = chunk_id
            else:
                break
        return best_id

    # Retire figures the current extractor no longer produces.
    #
    # Extraction dedupes on content hash, so without this a document keeps every
    # image any past version of the extractor ever emitted. That is not merely
    # untidy: the 79 full-page text rasters SQL_Cookbook_2006 yielded before
    # _exceeds_page_box existed stay queued for a vision call each -- hours of
    # model time on a CPU host, describing text already indexed verbatim -- and
    # a re-extract cannot clear them because it only ever adds.
    #
    # Guarded on the extractor having actually run. `extracted` is also empty
    # when the PDF could not be opened, and pruning on that path would delete a
    # document's entire image set because its file was briefly unreadable.
    retired_ids: list[str] = []
    if note is None and extracted:
        fresh_hashes = {img.content_hash for img in extracted}
        async with _database_module.get_session_factory()() as session:
            stale = (
                await session.execute(
                    select(ImageModel.id, ImageModel.path).where(
                        ImageModel.document_id == document_id,
                        ImageModel.content_hash.notin_(fresh_hashes),
                    )
                )
            ).all()
            retired_ids = [row[0] for row in stale]
            if retired_ids:
                await session.execute(
                    _delete(ImageModel).where(ImageModel.id.in_(retired_ids))
                )
                await session.commit()

        # Secondary indexes, each in its own transaction. An orphaned FTS row is
        # a far smaller problem than a prune that rolls back: images_fts is an
        # FTS5 virtual table created by db_init rather than by the model
        # metadata, so it is legitimately absent in some contexts and an error
        # here would poison the transaction that removed the rows.
        if retired_ids:
            try:
                async with _database_module.get_session_factory()() as session:
                    for image_id in retired_ids:
                        await session.execute(
                            _text("DELETE FROM images_fts WHERE image_id = :image_id"),
                            {"image_id": image_id},
                        )
                    await session.commit()
            except Exception as exc:
                logger.warning(
                    "image_extract_handler: could not clear images_fts for %d retired "
                    "image(s) doc=%s: %s",
                    len(retired_ids),
                    document_id,
                    exc,
                )

        if retired_ids:
            data_dir = Path(settings.DATA_DIR).expanduser()
            for _image_id, rel_path in stale:
                try:
                    (data_dir / rel_path).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("could not remove retired image %s: %s", rel_path, exc)
            # I-2: LanceDB is synchronous.
            await asyncio.to_thread(
                _vector_store_module.get_lancedb_service().delete_image_vectors,
                retired_ids,
            )
            existing_hashes &= fresh_hashes
            logger.info(
                "image_extract_handler: retired %d image(s) the current extractor "
                "no longer produces doc=%s",
                len(retired_ids),
                document_id,
            )

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
        async with _database_module.get_session_factory()() as session:
            session.add_all(new_images)
            await session.commit()

    # Analyze whatever still has no description, which is not the same set as
    # `new_images`. A re-extraction that only retires figures adds nothing, and
    # gating the enqueue on `new_images` left the images that SURVIVED the prune
    # undescribed with no job to describe them -- the one real figure in
    # SQL_Cookbook_2006 among them. Asking the question of the table also makes
    # this self-healing after an interrupted analyze run.
    async with _database_module.get_session_factory()() as session:
        undescribed = (
            await session.execute(
                select(func.count())
                .select_from(ImageModel)
                .where(
                    ImageModel.document_id == document_id,
                    ImageModel.description.is_(None),
                )
            )
        ).scalar_one()
        queued_already = (
            await session.execute(
                select(func.count())
                .select_from(EnrichmentJobModel)
                .where(
                    EnrichmentJobModel.document_id == document_id,
                    EnrichmentJobModel.job_type == "image_analyze",
                    EnrichmentJobModel.status.in_(["pending", "running"]),
                )
            )
        ).scalar_one()

    if undescribed and not queued_already:
        analyze_job_id = str(uuid.uuid4())
        async with _database_module.get_session_factory()() as session:
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

    async with _database_module.get_session_factory()() as session:
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
