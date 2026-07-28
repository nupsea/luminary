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

from app.models import Base, DocumentModel, EnrichmentJobModel
from app.services.image_extractor import (
    _MAX_DIM,
    _MIN_HEIGHT,
    _MIN_WIDTH,
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


def _pdf_with_vector_figure(path: Path, *, with_raster: bool = False) -> Path:
    """Write a one-page PDF whose only figure is drawn with vector strokes.

    This is the LaTeX/TikZ shape: the figure exists but page.get_images() sees
    nothing because no raster XObject was ever embedded.
    """
    doc = fitz.open()
    page = doc.new_page()
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
