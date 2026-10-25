"""Tests for GET /documents/{id}/cover endpoint."""

import uuid
from pathlib import Path

import fitz
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import ImageModel
from tests.factories import make_document


def _create_dummy_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((50, 50), "Test PDF Cover Page", fontsize=16)
    doc.save(str(path))
    doc.close()


async def test_get_document_cover_pdf(test_db):
    """GET /documents/{id}/cover generates and returns a WebP cover for a PDF."""
    _, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    pdf_path = tmp_path / f"{doc_id}.pdf"
    _create_dummy_pdf(pdf_path)

    async with factory() as session:
        doc = make_document(
            id=doc_id,
            title="Test PDF Document",
            format="pdf",
            word_count=100,
            page_count=1,
            file_path=str(pdf_path),
            stage="ready",
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First call: generates cover and caches it
        resp = await client.get(f"/documents/{doc_id}/cover")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"
        assert len(resp.content) > 0

        # Cached file must exist in DATA_DIR / covers / {id}.webp
        cover_cached = tmp_path / "covers" / f"{doc_id}.webp"
        assert cover_cached.is_file()

        # Second call: served directly from cache
        resp2 = await client.get(f"/documents/{doc_id}/cover")
        assert resp2.status_code == 200
        assert resp2.headers["content-type"] == "image/webp"


async def test_get_document_cover_from_image_model(test_db):
    """GET /documents/{id}/cover falls back to ImageModel figure when doc has no PDF."""
    _, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    # Create dummy image file
    images_dir = tmp_path / "images" / doc_id
    images_dir.mkdir(parents=True, exist_ok=True)
    img_file = images_dir / "diagram.png"
    img_file.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    async with factory() as session:
        doc = make_document(
            id=doc_id,
            title="Article with Diagram",
            form="article",
            domain="technical",
            word_count=500,
            page_count=1,
            file_path="",
            stage="ready",
        )
        img = ImageModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page=1,
            path=f"images/{doc_id}/diagram.png",
            width=100,
            height=100,
            content_hash="abc123hash",
            image_type="architecture_diagram",
        )
        session.add(doc)
        session.add(img)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/cover")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"


async def test_get_document_cover_epub(test_db):
    """GET /documents/{id}/cover extracts embedded cover image from an EPUB."""
    from io import BytesIO

    from ebooklib import epub
    from PIL import Image

    _, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    epub_path = tmp_path / f"{doc_id}.epub"

    book = epub.EpubBook()
    book.set_identifier(doc_id)
    book.set_title("Test EPUB Book")

    buf = BytesIO()
    Image.new("RGB", (60, 90), color="blue").save(buf, format="PNG")
    dummy_png = buf.getvalue()

    book.set_cover("cover.png", dummy_png)
    epub.write_epub(str(epub_path), book)

    async with factory() as session:
        doc = make_document(
            id=doc_id,
            title="Test EPUB Document",
            format="epub",
            word_count=50,
            file_path=str(epub_path),
            stage="ready",
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/cover")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"

        cover_cached = tmp_path / "covers" / f"{doc_id}.webp"
        assert cover_cached.is_file()


async def test_get_document_cover_404(test_db):
    """GET /documents/{id}/cover returns 404 when the document does not exist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{uuid.uuid4()}/cover")
        assert resp.status_code == 404


async def test_get_document_cover_204_when_document_has_no_image(test_db):
    """A coverless document answers 204, which the request log does not report as a failure."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            make_document(
                id=doc_id,
                title="Plain notes",
                form="entries",
                word_count=10,
                page_count=1,
                file_path="",
                stage="ready",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/cover")
        assert resp.status_code == 204
        assert resp.content == b""
