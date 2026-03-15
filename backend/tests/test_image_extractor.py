"""Unit tests for image_extractor.py -- S133."""
import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image as PILImage

from app.services.image_extractor import _MAX_DIM, _MIN_HEIGHT, _MIN_WIDTH, extract_images_pdf


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
