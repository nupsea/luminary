"""Tests for ImageEnricherService (S134).

Unit tests use in-memory SQLite + mocked LiteDB and LiteLLM.
Integration test (requires ollama llava) is guarded with pytest.mark.skipif.
"""

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, DocumentModel, ImageModel
from app.services.image_enricher import ImageEnricherService, _is_decorative

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rgb_png(path: Path, width: int, height: int, color: tuple) -> None:
    """Create a solid-color PNG at the given path."""
    img = PILImage.new("RGB", (width, height), color=color)
    img.save(str(path), format="PNG")


def _make_varied_png(path: Path, width: int = 200, height: int = 200) -> None:
    """Create a visually varied PNG (many unique colors)."""
    img = PILImage.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        for x in range(width):
            pixels.append(((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256))
    img.putdata(pixels)
    img.save(str(path), format="PNG")


# ---------------------------------------------------------------------------
# Pre-filter tests (pure function — no DB, no LLM)
# ---------------------------------------------------------------------------


def test_prefilter_solid_color_sets_decorative(tmp_path: Path) -> None:
    """A solid-color image (1 unique color) is decorative."""
    img_path = tmp_path / "solid.png"
    _make_rgb_png(img_path, 200, 200, (255, 255, 255))
    pil_img = PILImage.open(str(img_path))
    assert _is_decorative(pil_img) is True


def test_prefilter_few_colors_decorative(tmp_path: Path) -> None:
    """An image with fewer than 5 unique colors is decorative."""
    img = PILImage.new("RGB", (100, 100))
    pixels = [(i * 50, 0, 0) for i in range(4)] * 2500  # 4 unique colors
    img.putdata(pixels)
    assert _is_decorative(img) is True


def test_prefilter_ruleline_decorative(tmp_path: Path) -> None:
    """A 1000x50 image (aspect ratio 20:1) is decorative."""
    img_path = tmp_path / "rule.png"
    _make_rgb_png(img_path, 1000, 50, (0, 0, 0))
    pil_img = PILImage.open(str(img_path))
    assert _is_decorative(pil_img) is True


def test_prefilter_varied_image_not_decorative(tmp_path: Path) -> None:
    """A visually rich image is not decorative."""
    img_path = tmp_path / "varied.png"
    _make_varied_png(img_path)
    pil_img = PILImage.open(str(img_path))
    assert _is_decorative(pil_img) is False


# ---------------------------------------------------------------------------
# Async fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine(tmp_path: Path):
    """In-memory SQLite engine with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create images_fts FTS5 table
        from sqlalchemy import text  # noqa: PLC0415

        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS images_fts "
                "USING fts5(body, image_id UNINDEXED, document_id UNINDEXED)"
            )
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    """Return an async session factory bound to the in-memory engine."""
    return sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def doc_and_image(session_factory, tmp_path: Path):
    """Insert a DocumentModel and ImageModel with description=null.

    Returns (doc_id, image_id, img_path, data_dir).
    """
    doc_id = "doc-test-001"
    image_id = "img-test-001"

    img_path = tmp_path / "images" / doc_id
    img_path.mkdir(parents=True)
    full_img_path = img_path / "0_0.png"
    _make_varied_png(full_img_path)

    async with session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                file_path=str(tmp_path / "test.pdf"),
                format="pdf",
                content_type="book",
                stage="complete",
            )
        )
        # Use relative path matching DATA_DIR convention
        rel_path = f"images/{doc_id}/0_0.png"
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=None,
                page=0,
                path=rel_path,
                width=200,
                height=200,
                content_hash="abc123",
                image_type=None,
                description=None,
            )
        )
        await session.commit()

    return doc_id, image_id, full_img_path, tmp_path


# ---------------------------------------------------------------------------
# Unit tests with mocked LiteLLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_sets_description_and_image_type(
    doc_and_image, session_factory, tmp_path: Path
) -> None:
    """enrich() stores description and image_type; FTS5 indexes the description."""
    doc_id, image_id, img_path, data_dir = doc_and_image

    mock_response = MagicMock()
    mock_response.choices[0].message.content = (
        '{"image_type": "flowchart", '
        '"description": "A flowchart showing steps A to B", '
        '"components": ["A", "B"], "text": ""}'
    )

    mock_lancedb = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = [[0.1] * 384]

    with (
        patch(
            "app.services.llm.litellm.acompletion", new_callable=AsyncMock
        ) as mock_llm,
        patch("app.database.get_session_factory", return_value=session_factory),
        patch("app.config.get_settings") as mock_settings,
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        mock_llm.return_value = mock_response
        settings = MagicMock()
        settings.DATA_DIR = str(data_dir)
        settings.VISION_MODEL = "ollama/llava:7b"
        settings.OLLAMA_URL = "http://localhost:11434"
        settings.LITELLM_DEFAULT_MODEL = "ollama/gemma4"
        mock_settings.return_value = settings

        svc = ImageEnricherService()
        count = await svc.enrich(doc_id)

    assert count == 1

    # Verify SQLite row updated
    from sqlalchemy import select, text  # noqa: PLC0415

    async with session_factory() as session:
        row = (
            await session.execute(select(ImageModel).where(ImageModel.id == image_id))
        ).scalar_one_or_none()
        assert row is not None
        assert row.image_type == "flowchart"
        assert row.description == "A flowchart showing steps A to B"

        # Verify FTS5 indexed
        fts_result = await session.execute(
            text("SELECT image_id FROM images_fts WHERE images_fts MATCH 'steps'")
        )
        fts_ids = [r[0] for r in fts_result.fetchall()]
        assert image_id in fts_ids

    # Verify vector upserted
    mock_lancedb.upsert_image_vector.assert_called_once_with(
        image_id, doc_id, "A flowchart showing steps A to B", [0.1] * 384
    )


@pytest.mark.asyncio
async def test_decorative_image_skips_llm(session_factory, tmp_path: Path) -> None:
    """Solid-color image gets image_type='decorative' without any LLM call."""
    doc_id = "doc-decorative"
    image_id = "img-decorative"

    img_dir = tmp_path / "images" / doc_id
    img_dir.mkdir(parents=True)
    img_path = img_dir / "0_0.png"
    _make_rgb_png(img_path, 200, 200, (200, 200, 200))  # solid color

    async with session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Doc",
                file_path="/tmp/x.pdf",
                format="pdf",
                content_type="book",
                stage="complete",
            )
        )
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=None,
                page=0,
                path=f"images/{doc_id}/0_0.png",
                width=200,
                height=200,
                content_hash="deco123",
                image_type=None,
                description=None,
            )
        )
        await session.commit()

    mock_lancedb = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = [[0.0] * 384]

    with (
        patch(
            "app.services.llm.litellm.acompletion", new_callable=AsyncMock
        ) as mock_llm,
        patch("app.database.get_session_factory", return_value=session_factory),
        patch("app.config.get_settings") as mock_settings,
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.VISION_MODEL = "ollama/llava:7b"
        settings.OLLAMA_URL = "http://localhost:11434"
        settings.LITELLM_DEFAULT_MODEL = "ollama/gemma4"
        mock_settings.return_value = settings

        svc = ImageEnricherService()
        count = await svc.enrich(doc_id)

    assert count == 1
    # LLM must NOT have been called for a decorative image
    mock_llm.assert_not_called()

    from sqlalchemy import select  # noqa: PLC0415

    async with session_factory() as session:
        row = (
            await session.execute(select(ImageModel).where(ImageModel.id == image_id))
        ).scalar_one_or_none()
        assert row is not None
        assert row.image_type == "decorative"


@pytest.mark.asyncio
async def test_offline_503_propagates(doc_and_image, session_factory, tmp_path: Path) -> None:
    """When vision model returns 503, ServiceUnavailableError propagates."""
    import litellm as _litellm  # noqa: PLC0415

    doc_id, image_id, img_path, data_dir = doc_and_image

    mock_lancedb = MagicMock()
    mock_embedder = MagicMock()

    with (
        patch(
            "app.services.llm.litellm.acompletion",
            new_callable=AsyncMock,
            side_effect=_litellm.ServiceUnavailableError(
                message="Ollama unreachable", llm_provider="ollama", model="llava"
            ),
        ),
        patch("app.database.get_session_factory", return_value=session_factory),
        patch("app.config.get_settings") as mock_settings,
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(data_dir)
        settings.VISION_MODEL = "ollama/llava:7b"
        settings.OLLAMA_URL = "http://localhost:11434"
        settings.LITELLM_DEFAULT_MODEL = "ollama/gemma4"
        mock_settings.return_value = settings

        svc = ImageEnricherService()
        with pytest.raises(_litellm.ServiceUnavailableError):
            await svc.enrich(doc_id)

    # ImageModel description must remain null
    from sqlalchemy import select  # noqa: PLC0415

    async with session_factory() as session:
        row = (
            await session.execute(select(ImageModel).where(ImageModel.id == image_id))
        ).scalar_one_or_none()
        assert row is not None
        assert row.description is None


@pytest.mark.asyncio
async def test_images_fts_keyword_search(doc_and_image, session_factory, tmp_path: Path) -> None:
    """After enrich(), images_fts MATCH query returns the image_id."""
    doc_id, image_id, img_path, data_dir = doc_and_image

    mock_response = MagicMock()
    mock_response.choices[0].message.content = (
        '{"image_type": "chart", "description": "Bar chart comparing revenue figures", '
        '"components": [], "text": ""}'
    )
    mock_lancedb = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = [[0.0] * 384]

    with (
        patch(
            "app.services.llm.litellm.acompletion", new_callable=AsyncMock
        ) as mock_llm,
        patch("app.database.get_session_factory", return_value=session_factory),
        patch("app.config.get_settings") as mock_settings,
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        mock_llm.return_value = mock_response
        settings = MagicMock()
        settings.DATA_DIR = str(data_dir)
        settings.VISION_MODEL = "ollama/llava:7b"
        settings.OLLAMA_URL = "http://localhost:11434"
        settings.LITELLM_DEFAULT_MODEL = "ollama/gemma4"
        mock_settings.return_value = settings

        svc = ImageEnricherService()
        await svc.enrich(doc_id)

    from sqlalchemy import text  # noqa: PLC0415

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT image_id FROM images_fts WHERE images_fts MATCH 'revenue'")
        )
        found = [r[0] for r in result.fetchall()]
        assert image_id in found


# ---------------------------------------------------------------------------
# image_analyze_handler enqueue tail tests (S136)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_analyze_handler_enqueues_diagram_extract(
    session_factory,
) -> None:
    """After image_analyze completes, a diagram_extract job is enqueued when
    qualifying diagram images with descriptions exist.
    """

    from sqlalchemy import select  # noqa: PLC0415

    from app.models import EnrichmentJobModel  # noqa: PLC0415
    from app.services.image_enricher import image_analyze_handler  # noqa: PLC0415

    doc_id = "doc-enqueue-test"
    image_id = "img-enqueue-001"

    async with session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Enqueue Doc",
                file_path="/tmp/enqueue.pdf",
                format="pdf",
                content_type="book",
                stage="complete",
            )
        )
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=None,
                page=0,
                path=f"images/{doc_id}/0_0.png",
                width=200,
                height=200,
                content_hash="eq123",
                image_type="architecture_diagram",
                description="A component diagram showing Service A and Service B",
            )
        )
        await session.commit()

    with (
        patch(
            "app.services.image_enricher.ImageEnricherService.enrich",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("app.database.get_session_factory", return_value=session_factory),
    ):
        await image_analyze_handler(doc_id, "job-enqueue-001")

    async with session_factory() as session:
        jobs = (
            (
                await session.execute(
                    select(EnrichmentJobModel).where(
                        EnrichmentJobModel.document_id == doc_id,
                        EnrichmentJobModel.job_type == "diagram_extract",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(jobs) == 1
    assert jobs[0].status == "pending"


@pytest.mark.asyncio
async def test_image_analyze_handler_deduplication_skip(
    session_factory,
) -> None:
    """No duplicate diagram_extract job when one is already pending."""
    import uuid as _uuid  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.models import EnrichmentJobModel  # noqa: PLC0415
    from app.services.image_enricher import image_analyze_handler  # noqa: PLC0415

    doc_id = "doc-dedup-test"
    image_id = "img-dedup-001"

    async with session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Dedup Doc",
                file_path="/tmp/dedup.pdf",
                format="pdf",
                content_type="book",
                stage="complete",
            )
        )
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=None,
                page=0,
                path=f"images/{doc_id}/0_0.png",
                width=200,
                height=200,
                content_hash="dd123",
                image_type="sequence_diagram",
                description="A sequence diagram for auth flow",
            )
        )
        session.add(
            EnrichmentJobModel(
                id=str(_uuid.uuid4()),
                document_id=doc_id,
                job_type="diagram_extract",
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    with (
        patch(
            "app.services.image_enricher.ImageEnricherService.enrich",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("app.database.get_session_factory", return_value=session_factory),
    ):
        await image_analyze_handler(doc_id, "job-dedup-001")

    async with session_factory() as session:
        jobs = (
            (
                await session.execute(
                    select(EnrichmentJobModel).where(
                        EnrichmentJobModel.document_id == doc_id,
                        EnrichmentJobModel.job_type == "diagram_extract",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(jobs) == 1  # still only 1, not 2


@pytest.mark.asyncio
async def test_image_analyze_handler_no_qualifying_images_skips_enqueue(
    session_factory,
) -> None:
    """No diagram_extract job enqueued when no qualifying diagram images exist."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models import EnrichmentJobModel  # noqa: PLC0415
    from app.services.image_enricher import image_analyze_handler  # noqa: PLC0415

    doc_id = "doc-no-diag"
    image_id = "img-no-diag-001"

    async with session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="No Diag Doc",
                file_path="/tmp/nodiag.pdf",
                format="pdf",
                content_type="book",
                stage="complete",
            )
        )
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=None,
                page=0,
                path=f"images/{doc_id}/0_0.png",
                width=200,
                height=200,
                content_hash="nd123",
                image_type="chart",
                description="A bar chart",
            )
        )
        await session.commit()

    with (
        patch(
            "app.services.image_enricher.ImageEnricherService.enrich",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("app.database.get_session_factory", return_value=session_factory),
    ):
        await image_analyze_handler(doc_id, "job-nodiag-001")

    async with session_factory() as session:
        jobs = (
            (
                await session.execute(
                    select(EnrichmentJobModel).where(
                        EnrichmentJobModel.document_id == doc_id,
                        EnrichmentJobModel.job_type == "diagram_extract",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(jobs) == 0


# ---------------------------------------------------------------------------
# Integration test — requires ollama with llava model
# ---------------------------------------------------------------------------


def _ollama_has_llava() -> bool:
    """Return True if ollama is in PATH and llava model is listed."""
    if not shutil.which("ollama"):
        return False
    import subprocess  # noqa: PLC0415

    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        return "llava:7b" in result.stdout
    except Exception:
        return False


_HAS_OLLAMA = _ollama_has_llava()


@pytest.mark.skipif(not _HAS_OLLAMA, reason="ollama not available in this environment")
@pytest.mark.asyncio
async def test_integration_vision_analysis_real_image(tmp_path: Path) -> None:
    """Integration: enrich() calls real vision LLM and stores description.

    Requires: ollama running with llava:13b pulled.
    Skipped automatically if ollama is not in PATH.
    """
    from app.services.image_enricher import ImageEnricherService  # noqa: PLC0415

    # Create a simple diagram-like image (not solid-color, not decorative)
    img_dir = tmp_path / "images" / "integ-doc"
    img_dir.mkdir(parents=True)
    img_path = img_dir / "0_0.png"
    _make_varied_png(img_path, 300, 200)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import text  # noqa: PLC0415

        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS images_fts "
                "USING fts5(body, image_id UNINDEXED, document_id UNINDEXED)"
            )
        )

    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    doc_id = "integ-doc"
    image_id = "integ-img-001"

    async with sf() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Integration Doc",
                file_path="/tmp/x.pdf",
                format="pdf",
                content_type="book",
                stage="complete",
            )
        )
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=None,
                page=0,
                path=f"images/{doc_id}/0_0.png",
                width=300,
                height=200,
                content_hash="integ123",
                image_type=None,
                description=None,
            )
        )
        await session.commit()

    mock_lancedb = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = [[0.1] * 384]

    with (
        patch("app.database.get_session_factory", return_value=sf),
        patch("app.config.get_settings") as mock_settings,
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.VISION_MODEL = "ollama/llava:7b"
        settings.OLLAMA_URL = "http://localhost:11434"
        settings.LITELLM_DEFAULT_MODEL = "ollama/gemma4"
        mock_settings.return_value = settings

        svc = ImageEnricherService()
        count = await svc.enrich(doc_id)

    assert count == 1

    from sqlalchemy import select  # noqa: PLC0415

    async with sf() as session:
        row = (
            await session.execute(select(ImageModel).where(ImageModel.id == image_id))
        ).scalar_one_or_none()
        assert row is not None
        assert row.description is not None and len(row.description) > 0
        assert row.image_type is not None

    await engine.dispose()
