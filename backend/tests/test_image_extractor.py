"""Unit tests for image_extractor.py -- S133."""

import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest
import pytest_asyncio
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, DocumentModel, EnrichmentJobModel, ImageModel
from app.services.image_extractor import (
    _MAX_DIM,
    _MIN_HEIGHT,
    _MIN_WIDTH,
    _is_prose_block,
    extract_images_pdf,
    image_extract_handler,
)


def _make_png_bytes(w: int, h: int, color: tuple[int, int, int] = (200, 200, 200)) -> bytes:
    """Create a minimal valid PNG in memory."""
    img = PILImage.new("RGB", (w, h), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mock_fitz_doc(images_per_page: list[list[bytes]]):
    """Build a minimal fitz.Document mock from per-page image bytes lists."""
    pages = []
    xref_counter = [0]
    xref_map: dict[int, bytes] = {}

    for page_bytes_list in images_per_page:
        page_image_list = []
        for raw in page_bytes_list:
            xref_counter[0] += 1
            xref = xref_counter[0]
            xref_map[xref] = raw
            page_image_list.append((xref, 0, 0, 0, 8, "", "", ""))
        mock_page = MagicMock()
        mock_page.get_images.return_value = page_image_list
        mock_page.get_drawings.return_value = []
        pages.append(mock_page)

    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: len(pages)
    mock_doc.__getitem__ = lambda self, i: pages[i]
    mock_doc.extract_image.side_effect = lambda xref: {"image": xref_map[xref]}
    return mock_doc


def test_image_below_min_size_skipped(tmp_path):
    """Images below 150x100 must not be stored."""
    small_png = _make_png_bytes(100, 50)
    mock_doc = _mock_fitz_doc([[small_png]])

    with patch("fitz.open", return_value=mock_doc):
        results = extract_images_pdf(Path("/fake/doc.pdf"), tmp_path, "test-doc")

    assert results == [], "Small image should be skipped"


def test_image_above_max_size_skipped_with_warning(tmp_path, caplog):
    """Images above 4000x4000 must be skipped and a warning logged."""
    import logging

    large_png = _make_png_bytes(4001, 4001)
    mock_doc = _mock_fitz_doc([[large_png]])

    with patch("fitz.open", return_value=mock_doc):
        with caplog.at_level(logging.WARNING, logger="app.services.image_extractor"):
            results = extract_images_pdf(Path("/fake/doc.pdf"), tmp_path, "test-doc")

    assert results == [], "Oversized image should be skipped"
    assert any("oversized" in r.message.lower() or "4001" in r.message for r in caplog.records)


def test_sha256_dedup_same_bytes(tmp_path):
    """Same image bytes on different xrefs should yield only one stored file."""
    png_bytes = _make_png_bytes(200, 200)
    # Two xrefs with identical bytes on the same page
    mock_doc = _mock_fitz_doc([[png_bytes, png_bytes]])

    with patch("fitz.open", return_value=mock_doc):
        results = extract_images_pdf(Path("/fake/doc.pdf"), tmp_path, "test-doc")

    assert len(results) == 1, "Duplicate bytes should produce only one result"
    expected_hash = hashlib.sha256(png_bytes).hexdigest()
    assert results[0].content_hash == expected_hash


def test_valid_image_stored(tmp_path):
    """A valid 200x200 image should be extracted and saved as PNG."""
    png_bytes = _make_png_bytes(200, 200)
    mock_doc = _mock_fitz_doc([[png_bytes]])

    with patch("fitz.open", return_value=mock_doc):
        results = extract_images_pdf(Path("/fake/doc.pdf"), tmp_path, "test-doc")

    assert len(results) == 1
    assert results[0].width == 200
    assert results[0].height == 200
    assert results[0].abs_path.exists(), "PNG file should be written to disk"


def test_min_size_constants():
    """Sanity check size constants."""
    assert _MIN_WIDTH == 150
    assert _MIN_HEIGHT == 100
    assert _MAX_DIM == 4000


def _pdf_with_vector_figure(
    path: Path, *, with_raster: bool = False, with_background: bool = False
) -> Path:
    """Write a one-page PDF whose only figure is drawn with vector strokes.

    This is the LaTeX/TikZ shape: the figure exists but page.get_images() sees
    nothing because no raster XObject was ever embedded.
    """
    doc = fitz.open()
    page = doc.new_page()
    if with_background:
        page.draw_rect(page.rect, color=(0.95, 0.95, 0.95), fill=(0.95, 0.95, 0.95))
    page.insert_text(fitz.Point(72, 60), "Figure 1: a vector-drawn diagram")
    for row in range(12):
        for col in range(12):
            x = 150 + col * 18
            y = 200 + row * 18
            page.draw_line(fitz.Point(x, y), fitz.Point(x + 14, y + 14), color=(0, 0, 0), width=1)
    if with_raster:
        page.insert_image(fitz.Rect(150, 500, 450, 700), stream=_make_png_bytes(300, 200))
    doc.save(str(path))
    doc.close()
    return path


def test_vector_figure_extracted_when_page_has_no_raster(tmp_path):
    """A vector-drawn figure must be rasterized when get_images() finds nothing."""
    pdf = _pdf_with_vector_figure(tmp_path / "vector.pdf")

    results = extract_images_pdf(pdf, tmp_path / "out", "vec-doc")

    assert len(results) == 1, "The vector figure should have been recovered"
    assert results[0].abs_path.exists()
    assert "_v" in results[0].abs_path.name, "Vector figures use the _v filename marker"


def test_page_spanning_primitive_does_not_swallow_the_figure(tmp_path):
    """A background wash must not bridge every cluster into one rejected region.

    The wash spans the occupancy grid, so without excluding it up front the
    figure merges into a whole-page component that the page-fraction guard then
    discards -- taking the real figure with it.
    """
    pdf = _pdf_with_vector_figure(tmp_path / "washed.pdf", with_background=True)

    results = extract_images_pdf(pdf, tmp_path / "out", "wash-doc")

    assert len(results) == 1, "The figure must survive a full-page background"
    assert "_v" in results[0].abs_path.name


def test_vector_fallback_can_be_disabled(tmp_path):
    """vector_fallback=False restores raster-only behaviour."""
    pdf = _pdf_with_vector_figure(tmp_path / "vector.pdf")

    results = extract_images_pdf(pdf, tmp_path / "out", "vec-doc", vector_fallback=False)

    assert results == []


def test_vector_fallback_skipped_when_page_has_raster(tmp_path):
    """A page that already yielded a raster image is not rasterized again."""
    pdf = _pdf_with_vector_figure(tmp_path / "mixed.pdf", with_raster=True)

    results = extract_images_pdf(pdf, tmp_path / "out", "mixed-doc")

    assert len(results) == 1
    assert "_v" not in results[0].abs_path.name


def test_rules_and_underlines_are_not_figures(tmp_path):
    """Header rules and text underlines must not be mistaken for figures."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 100), "A page of prose with a header rule")
    page.draw_line(fitz.Point(72, 80), fitz.Point(520, 80), width=0.8)
    page.draw_line(fitz.Point(72, 300), fitz.Point(180, 300), width=0.8)
    page.draw_line(fitz.Point(72, 500), fitz.Point(240, 500), width=0.8)
    pdf = tmp_path / "prose.pdf"
    doc.save(str(pdf))
    doc.close()

    results = extract_images_pdf(pdf, tmp_path / "out", "prose-doc")

    assert results == [], "Rule lines are not figures"


def _pdf_from_reflowed_source(path: Path) -> Path:
    """A page whose only 'drawings' are a flowed-column background and a rule.

    The EPUB-to-PDF shape. The generator emits one fill rectangle spanning the
    whole *flow* -- here 20x the page height -- which the layout engine then
    clips to each page. Clipped, it is exactly the page's text column, so every
    geometric test downstream reads a page of prose as a figure. Measured on
    SQL_Cookbook_2006: 81 images extracted, 79 of them full pages of body text.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(
        fitz.Rect(72, -7000, 540, 8840),  # 15,840pt tall on a 792pt page
        color=(0.98, 0.98, 0.98),
        fill=(0.98, 0.98, 0.98),
    )
    for i in range(30):
        page.insert_text(fitz.Point(72, 90 + i * 22), "Body text that flows down the column.")
    page.draw_rect(fitz.Rect(90, 600, 500, 700), color=(0.95, 0.95, 0.95), fill=(0.95, 0.95, 0.95))
    page.draw_line(fitz.Point(72, 560), fitz.Point(540, 560), width=0.8)
    doc.save(str(path))
    doc.close()
    return path


def test_flowed_column_background_is_not_a_figure(tmp_path):
    """A primitive larger than its page is a column container, not ink.

    The measurement has to happen before clipping: clipped to the page, this
    rectangle is 0.765 of the page area and passes _MAX_FIGURE_PAGE_FRACTION.
    """
    pdf = _pdf_from_reflowed_source(tmp_path / "reflowed.pdf")

    results = extract_images_pdf(pdf, tmp_path / "out", "reflow-doc")

    assert results == [], "A page of prose is not a figure"


def test_a_real_figure_survives_a_flowed_column_background(tmp_path):
    """The guard must remove the container without taking the figure with it."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(
        fitz.Rect(72, -7000, 540, 8840),
        color=(0.98, 0.98, 0.98),
        fill=(0.98, 0.98, 0.98),
    )
    for row in range(12):
        for col in range(12):
            x, y = 150 + col * 18, 200 + row * 18
            page.draw_line(fitz.Point(x, y), fitz.Point(x + 14, y + 14), width=1)
    pdf = tmp_path / "figure_in_flow.pdf"
    doc.save(str(pdf))
    doc.close()

    results = extract_images_pdf(pdf, tmp_path / "out", "flow-fig-doc")

    assert len(results) == 1, "The figure must survive removal of the column background"
    assert "_v" in results[0].abs_path.name


def test_bordered_paragraph_is_not_a_figure(tmp_path):
    """A TIP/NOTE callout is a paragraph someone drew a border around.

    Three primitives around prose passes every geometric test, and the vision
    model duly reports "the image displays a section of text" -- for a paragraph
    ingestion already chunked and indexed verbatim.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(90, 200, 500, 380), width=1)
    page.draw_line(fitz.Point(90, 240), fitz.Point(500, 240), width=0.8)
    page.draw_rect(fitz.Rect(95, 205, 495, 235), color=(0.95, 0.95, 0.95), fill=(0.95, 0.95, 0.95))
    page.insert_text(fitz.Point(250, 228), "TIP", fontsize=12)
    for i in range(6):
        page.insert_text(
            fitz.Point(100, 262 + i * 18),
            "For more on CONNECT BY and related features, see the Oracle",
            fontsize=10,
        )
    pdf = tmp_path / "callout.pdf"
    doc.save(str(pdf))
    doc.close()

    results = extract_images_pdf(pdf, tmp_path / "out", "callout-doc")

    assert results == [], "A bordered paragraph is not a figure"


def test_densely_labelled_diagram_is_not_read_as_prose():
    """A compact diagram whose labels are PDF text must not be read as prose.

    ResNet's Figure 2 -- the residual block, four labels inside 102x96pt -- is
    denser in text-by-area (0.212) than three of the four SQL Cookbook callouts,
    so a text-coverage threshold drops it and an earlier version of this guard
    did. Line *shape* is what separates them: a paragraph's lines span the box
    that contains them, a diagram's labels annotate geometry and do not.

    Measured full-width-line shares, over 96 candidate regions from five
    documents: ResNet Fig 2 0.143, the widest real figure (Adam Fig 3) 0.176,
    the narrowest prose block 0.333.
    """
    doc = fitz.open()
    page = doc.new_page()
    # Four short labels scattered across a 150x120pt region, as a diagram's are.
    page.insert_text(fitz.Point(158, 220), "weight layer", fontsize=9)
    page.insert_text(fitz.Point(158, 280), "weight layer", fontsize=9)
    page.insert_text(fitz.Point(230, 250), "relu", fontsize=9)
    page.insert_text(fitz.Point(230, 312), "relu", fontsize=9)

    assert _is_prose_block(page, fitz.Rect(150, 200, 320, 320)) is False
    doc.close()


def test_bordered_prose_is_read_as_prose():
    """The other side of the same threshold: lines that span their box."""
    doc = fitz.open()
    page = doc.new_page()
    for i in range(6):
        page.insert_text(
            fitz.Point(100, 262 + i * 18),
            "For more on CONNECT BY and related features, see the Oracle",
            fontsize=10,
        )

    assert _is_prose_block(page, fitz.Rect(90, 240, 500, 380)) is True
    doc.close()


def test_prose_guard_refuses_to_judge_a_short_label_run(tmp_path):
    """Below three lines there is no paragraph shape to read.

    A figure carrying one wide caption line inside its bbox would otherwise
    score a full-width-line share of 1.0 and be discarded.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(100, 300), "a single very wide label spanning the region", 
                     fontsize=11)
    bbox = fitz.Rect(90, 280, 400, 340)

    assert _is_prose_block(page, bbox) is False
    doc.close()


@pytest_asyncio.fixture
async def handler_db():
    """In-memory SQLite engine with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_doc_and_job(factory, doc_id: str, job_id: str, file_path: Path):
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Broken PDF",
                file_path=str(file_path),
                format="pdf",
                content_type="paper",
                stage="enriching",
            )
        )
        session.add(
            EnrichmentJobModel(
                id=job_id,
                document_id=doc_id,
                job_type="image_extract",
                status="running",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_handler_degrades_when_pdf_cannot_be_opened(handler_db, tmp_path):
    """An unreadable PDF must leave the document usable, not stuck enriching."""
    doc_id, job_id = "doc-broken", "job-broken"
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not really a pdf")
    await _seed_doc_and_job(handler_db, doc_id, job_id, bad_pdf)

    with (
        patch("app.database.get_session_factory", return_value=handler_db),
        patch("app.config.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.PDF_VECTOR_FIGURES = True
        mock_settings.return_value = settings

        await image_extract_handler(doc_id, job_id)

    async with handler_db() as session:
        doc = (
            await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        job = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()

    assert doc.stage == "complete", "The handler must finish rather than abort on the error"
    assert job.error_message and "Image extraction failed" in job.error_message


@pytest.mark.asyncio
async def test_reextraction_retires_images_the_extractor_no_longer_produces(
    handler_db, tmp_path
):
    """A document must not keep figures a past extractor version emitted.

    Extraction dedupes on content hash, so a re-extract only ever added. The 79
    full-page text rasters SQL_Cookbook_2006 yielded before _exceeds_page_box
    existed therefore stayed queued for a vision call each, and no re-extract
    could clear them.
    """
    doc_id, job_id = "doc-retire", "job-retire"
    pdf = _pdf_with_vector_figure(tmp_path / "fig.pdf")
    await _seed_doc_and_job(handler_db, doc_id, job_id, pdf)

    stale_id = "11111111-2222-3333-4444-555555555555"
    stale_rel = f"images/{doc_id}/stale.png"
    stale_abs = tmp_path / stale_rel
    stale_abs.parent.mkdir(parents=True, exist_ok=True)
    stale_abs.write_bytes(_make_png_bytes(200, 200))
    async with handler_db() as session:
        session.add(
            ImageModel(
                id=stale_id,
                document_id=doc_id,
                page=3,
                path=stale_rel,
                width=200,
                height=200,
                content_hash="a-hash-this-pdf-does-not-produce",
                description="The image displays a section of text.",
            )
        )
        await session.commit()

    lancedb = MagicMock()
    with (
        patch("app.database.get_session_factory", return_value=handler_db),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.services.vector_store.get_lancedb_service", return_value=lancedb
        ),
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.PDF_VECTOR_FIGURES = True
        mock_settings.return_value = settings

        await image_extract_handler(doc_id, job_id)

    async with handler_db() as session:
        remaining = (
            await session.execute(
                select(ImageModel.content_hash).where(ImageModel.document_id == doc_id)
            )
        ).scalars().all()

    assert "a-hash-this-pdf-does-not-produce" not in remaining, "stale row must be gone"
    assert len(remaining) == 1, "the figure this PDF does produce must be kept"
    assert not stale_abs.exists(), "the retired PNG must be removed from disk"
    lancedb.delete_image_vectors.assert_called_once_with([stale_id])


@pytest.mark.asyncio
async def test_a_failed_extraction_never_retires_anything(handler_db, tmp_path):
    """The prune is guarded on the extractor having actually run.

    `extracted` is empty both when a document has no figures and when its file
    could not be opened. Pruning on the second would delete a document's whole
    image set because its file was briefly unreadable.
    """
    doc_id, job_id = "doc-noprune", "job-noprune"
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not really a pdf")
    await _seed_doc_and_job(handler_db, doc_id, job_id, bad_pdf)

    async with handler_db() as session:
        session.add(
            ImageModel(
                id="99999999-8888-7777-6666-555555555555",
                document_id=doc_id,
                page=0,
                path=f"images/{doc_id}/keep.png",
                width=300,
                height=300,
                content_hash="hash-that-must-survive",
            )
        )
        await session.commit()

    with (
        patch("app.database.get_session_factory", return_value=handler_db),
        patch("app.config.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.PDF_VECTOR_FIGURES = True
        mock_settings.return_value = settings

        await image_extract_handler(doc_id, job_id)

    async with handler_db() as session:
        remaining = (
            await session.execute(
                select(ImageModel.content_hash).where(ImageModel.document_id == doc_id)
            )
        ).scalars().all()

    assert remaining == ["hash-that-must-survive"]


@pytest.mark.asyncio
async def test_handler_notes_when_a_pdf_yields_no_images(handler_db, tmp_path):
    """A silently image-free document gets an explanation on its job."""
    doc_id, job_id = "doc-empty", "job-empty"
    doc = fitz.open()
    doc.new_page().insert_text(fitz.Point(72, 100), "Prose only, no figures.")
    empty_pdf = tmp_path / "prose.pdf"
    doc.save(str(empty_pdf))
    doc.close()
    await _seed_doc_and_job(handler_db, doc_id, job_id, empty_pdf)

    with (
        patch("app.database.get_session_factory", return_value=handler_db),
        patch("app.config.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.PDF_VECTOR_FIGURES = True
        mock_settings.return_value = settings

        await image_extract_handler(doc_id, job_id)

    async with handler_db() as session:
        job = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()
        stage = (
            await session.execute(select(DocumentModel.stage).where(DocumentModel.id == doc_id))
        ).scalar_one()

    assert stage == "complete"
    assert job.error_message == "No images found in this document."


def test_blank_render_is_not_stored(tmp_path):
    """A region that rasterizes to a flat wash must not cost a vision call.

    Figure backgrounds are often drawn as a filled white rectangle; clustering
    fences one off like any other primitive, but there is nothing in it to see.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(150, 200, 450, 400), color=(1, 1, 1), fill=(1, 1, 1))
    page.draw_rect(fitz.Rect(155, 205, 445, 395), color=(1, 1, 1), fill=(1, 1, 1))
    page.draw_rect(fitz.Rect(160, 210, 440, 390), color=(1, 1, 1), fill=(1, 1, 1))
    pdf = tmp_path / "blank_box.pdf"
    doc.save(str(pdf))
    doc.close()

    results = extract_images_pdf(pdf, tmp_path / "out", "blank-doc")

    assert results == [], "A flat render carries no analyzable content"
