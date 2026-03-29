"""Tests for S187: GET /chat/suggestions endpoint.

Covers:
  (a) test_suggestions_book_document: book doc returns suggestions with entity names
  (b) test_suggestions_null_document_id: null document_id returns cross-document suggestions
  (c) test_suggestions_technical_document: tech doc returns concept/tradeoff suggestions
  (d) test_suggestions_video_document: video doc returns argument/evidence suggestions
  (e) test_suggestions_empty_library: no documents returns onboarding suggestions
  (f) test_suggestions_returns_four: always returns exactly 4 suggestions
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.database as db_module
from app.db_init import create_all_tables
from app.models import DocumentModel, SectionModel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def db_session():
    """In-memory SQLite with full schema for document/section queries."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_factory = db_module._session_factory
    orig_engine = db_module._engine
    db_module._engine = engine
    db_module._session_factory = factory
    async with factory() as session:
        yield session
    db_module._session_factory = orig_factory
    db_module._engine = orig_engine
    await engine.dispose()


def _make_doc(doc_id: str, title: str, content_type: str) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=title,
        format="txt",
        content_type=content_type,
        word_count=1000,
        page_count=10,
        file_path=f"/tmp/{doc_id}.txt",
    )


def _make_section(doc_id: str, heading: str, order: int) -> SectionModel:
    return SectionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        heading=heading,
        level=1,
        section_order=order,
    )


# ---------------------------------------------------------------------------
# (a) Book document returns suggestions with entity names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_book_document(db_session):
    """Book doc with PERSON and CONCEPT entities returns character/theme suggestions."""
    doc = _make_doc("doc-book-1", "The Odyssey", "book")
    db_session.add(doc)
    db_session.add(_make_section("doc-book-1", "The Journey Home", 1))
    db_session.add(_make_section("doc-book-1", "The Sirens", 2))
    await db_session.commit()

    entities = {
        "PERSON": ["Ulysses", "Penelope"],
        "CONCEPT": ["hospitality", "loyalty"],
        "PLACE": ["Ithaca"],
    }

    with patch(
        "app.routers.chat_meta.get_graph_service"
    ) as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities
        # Import after patching
        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-book-1")

    assert len(result.suggestions) == 4
    # At least one suggestion should mention Ulysses (top PERSON entity)
    all_text = " ".join(result.suggestions)
    assert "Ulysses" in all_text


# ---------------------------------------------------------------------------
# (b) Null document_id returns cross-document suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_null_document_id(db_session):
    """Null document_id returns cross-document entity suggestions."""
    shared_entities = ["quantum entanglement", "Schrodinger", "wave function"]

    with patch(
        "app.routers.chat_meta.get_graph_service"
    ) as mock_graph:
        mock_graph.return_value.get_cross_document_entities.return_value = shared_entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id=None)

    assert len(result.suggestions) == 4
    all_text = " ".join(result.suggestions)
    assert "quantum entanglement" in all_text


# ---------------------------------------------------------------------------
# (c) Technical document returns concept/tradeoff suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_technical_document(db_session):
    """Tech doc with CONCEPT and TECHNOLOGY entities returns tradeoff suggestions."""
    doc = _make_doc("doc-tech-1", "System Design Guide", "tech_book")
    db_session.add(doc)
    db_session.add(_make_section("doc-tech-1", "Caching Strategies", 1))
    await db_session.commit()

    entities = {
        "CONCEPT": ["consistency", "availability"],
        "TECHNOLOGY": ["Redis", "PostgreSQL"],
    }

    with patch(
        "app.routers.chat_meta.get_graph_service"
    ) as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-tech-1")

    assert len(result.suggestions) == 4
    all_text = " ".join(result.suggestions)
    assert "consistency" in all_text or "Redis" in all_text


# ---------------------------------------------------------------------------
# (d) Video document returns argument/evidence suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_video_document(db_session):
    """Video doc with CONCEPT and PERSON entities returns argument suggestions."""
    doc = _make_doc("doc-video-1", "AI Lecture", "video")
    db_session.add(doc)
    await db_session.commit()

    entities = {
        "CONCEPT": ["neural networks", "backpropagation"],
        "PERSON": ["Geoffrey Hinton"],
    }

    with patch(
        "app.routers.chat_meta.get_graph_service"
    ) as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-video-1")

    assert len(result.suggestions) == 4
    all_text = " ".join(result.suggestions)
    assert "neural networks" in all_text or "Hinton" in all_text


# ---------------------------------------------------------------------------
# (e) Empty library returns onboarding suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_empty_library(db_session):
    """No cross-document entities returns onboarding suggestions."""
    with patch(
        "app.routers.chat_meta.get_graph_service"
    ) as mock_graph:
        mock_graph.return_value.get_cross_document_entities.return_value = []

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id=None)

    assert len(result.suggestions) == 4
    all_text = " ".join(result.suggestions)
    assert "Upload" in all_text or "import" in all_text.lower()


# ---------------------------------------------------------------------------
# (f) Always returns exactly 4 suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_returns_four(db_session):
    """Even with minimal entity data, suggestions list has exactly 4 items."""
    doc = _make_doc("doc-sparse-1", "Sparse Doc", "notes")
    db_session.add(doc)
    await db_session.commit()

    # Only one entity, no headings -> should still pad to 4
    entities = {"CONCEPT": ["one-concept"]}

    with patch(
        "app.routers.chat_meta.get_graph_service"
    ) as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-sparse-1")

    assert len(result.suggestions) == 4
