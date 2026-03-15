"""Integration tests for images API endpoints -- S133."""
import uuid
from datetime import UTC, datetime
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, EnrichmentJobModel, ImageModel


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_images_returns_empty_for_text_doc(test_db):
    """GET /documents/{id}/images returns [] for a text-only document (not 404)."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(DocumentModel(
            id=doc_id,
            title="Text Book",
            format="txt",
            content_type="book",
            word_count=100,
            page_count=0,
            file_path="/fake.txt",
            stage="complete",
        ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_images_returns_404_for_unknown_doc(test_db):
    """GET /documents/{unknown}/images returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/nonexistent-id/images")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_images_returns_stored_image(test_db):
    """GET /documents/{id}/images returns the stored ImageModel rows."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    img_id = str(uuid.uuid4())

    # Create a fake PNG file at the expected path
    images_dir = tmp_path / "images" / doc_id
    images_dir.mkdir(parents=True, exist_ok=True)
    fake_png = images_dir / "0_0.png"
    fake_png.write_bytes(b"fake png content")

    async with factory() as session:
        session.add(DocumentModel(
            id=doc_id,
            title="PDF Book",
            format="pdf",
            content_type="book",
            word_count=1000,
            page_count=10,
            file_path="/fake.pdf",
            stage="complete",
        ))
        session.add(ImageModel(
            id=img_id,
            document_id=doc_id,
            chunk_id=None,
            page=0,
            path=f"images/{doc_id}/0_0.png",
            width=300,
            height=200,
            content_hash="abc123",
            created_at=datetime.now(UTC),
        ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == img_id
    assert data["items"][0]["width"] == 300
    assert data["items"][0]["height"] == 200


@pytest.mark.asyncio
async def test_serve_image_raw_returns_200(test_db):
    """GET /images/{id}/raw returns 200 with image/png for a stored image."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    img_id = str(uuid.uuid4())

    images_dir = tmp_path / "images" / doc_id
    images_dir.mkdir(parents=True, exist_ok=True)
    png_path = images_dir / "0_0.png"
    # Write a valid 1x1 PNG
    img = PILImage.new("RGB", (1, 1), (128, 128, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_path.write_bytes(buf.getvalue())

    async with factory() as session:
        session.add(DocumentModel(
            id=doc_id,
            title="PDF Book",
            format="pdf",
            content_type="book",
            word_count=100,
            page_count=1,
            file_path="/fake.pdf",
            stage="complete",
        ))
        session.add(ImageModel(
            id=img_id,
            document_id=doc_id,
            chunk_id=None,
            page=0,
            path=f"images/{doc_id}/0_0.png",
            width=1,
            height=1,
            content_hash="deadbeef",
            created_at=datetime.now(UTC),
        ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/images/{img_id}/raw")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_serve_image_raw_404_for_missing_image(test_db):
    """GET /images/{unknown}/raw returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/images/nonexistent-image-id/raw")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_enrichment_returns_jobs(test_db):
    """GET /documents/{id}/enrichment returns enrichment job rows."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(DocumentModel(
            id=doc_id,
            title="PDF Book",
            format="pdf",
            content_type="book",
            word_count=100,
            page_count=1,
            file_path="/fake.pdf",
            stage="enriching",
        ))
        session.add(EnrichmentJobModel(
            id=job_id,
            document_id=doc_id,
            job_type="image_extract",
            status="pending",
            created_at=datetime.now(UTC),
        ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/enrichment")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "image_extract"
    assert jobs[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_enrichment_returns_empty_for_text_doc(test_db):
    """GET /documents/{id}/enrichment returns [] for a doc with no enrichment jobs."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(DocumentModel(
            id=doc_id,
            title="Text Book",
            format="txt",
            content_type="book",
            word_count=100,
            page_count=0,
            file_path="/fake.txt",
            stage="complete",
        ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/enrichment")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_enrichment_returns_404_for_unknown_doc(test_db):
    """GET /documents/{unknown}/enrichment returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/nonexistent-id/enrichment")
    assert resp.status_code == 404
