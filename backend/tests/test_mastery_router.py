"""Tests for mastery router endpoints (S145).

AC6: GET /mastery/concepts returns sorted list with mastery, card_count, due_soon, no_flashcards
AC7: GET /mastery/heatmap returns chapter x concept grid
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    DocumentModel,
    SectionModel,
)


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
    from app.config import get_settings

    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_mastery_concepts_empty(test_db):
    """AC6: GET /mastery/concepts with nonexistent document_id returns 200 with empty list."""
    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_entities_by_type_for_document.return_value = {}
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/mastery/concepts",
                params={"document_ids": str(uuid.uuid4())},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "concepts" in data
    assert isinstance(data["concepts"], list)
    assert len(data["concepts"]) == 0  # no entities, no mastery


@pytest.mark.asyncio
async def test_get_mastery_heatmap_empty(test_db):
    """AC7: GET /mastery/heatmap with nonexistent document_id returns 200 empty."""
    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_entities_by_type_for_document.return_value = {}
        mock_graph_factory.return_value = mock_graph

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/mastery/heatmap",
                params={"document_id": str(uuid.uuid4())},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["chapters"] == []
    assert data["concepts"] == []
    assert data["cells"] == []


@pytest.mark.asyncio
async def test_get_mastery_heatmap_with_data(test_db):
    """AC7: heatmap returns cells with mastery=None when no flashcards."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Tech Book",
                format="txt",
                content_type="tech_book",
                page_count=5,
                file_path="/tmp/x.pdf",
                stage="complete",
            )
        )
        session.add(
            SectionModel(
                id=section_id,
                document_id=doc_id,
                heading="Chapter 1: Closures",
                level=1,
                section_order=0,
            )
        )
        await session.commit()

    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_entities_by_type_for_document.return_value = {
            "CONCEPT": ["closures"]
        }
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/mastery/heatmap",
                params={"document_id": doc_id},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "Chapter 1: Closures" in data["chapters"]
    assert "closures" in data["concepts"]
    # No flashcards -> mastery should be null
    cell = next(
        (c for c in data["cells"] if c["chapter"] == "Chapter 1: Closures"), None
    )
    assert cell is not None
    assert cell["mastery"] is None
    assert cell["card_count"] == 0
