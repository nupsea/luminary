"""Tests for GET /chat/suggestions endpoint (S187 baseline + S195 Bloom-progressive).

Covers:
  (a) test_suggestions_book_document: book doc returns suggestions with entity names
  (b) test_suggestions_null_document_id: null document_id returns cross-document suggestions
  (c) test_suggestions_technical_document: tech doc returns concept/tradeoff suggestions
  (d) test_suggestions_video_document: video doc returns argument/evidence suggestions
  (e) test_suggestions_empty_library: no documents returns onboarding suggestions
  (f) test_suggestions_returns_four: always returns exactly 4 suggestions
  (g) test_suggestions_not_in_history: AC11 -- returned suggestions not in recent history
  (h) test_bloom_level_decrease: AC12 -- bloom level decreases per 4 asked questions
  (i) test_fallback_on_llm_unavailable: AC13 -- fallback to templates when LLM raises
  (j) test_jaccard_filter: AC14 -- near-duplicate filtered out at threshold > 0.7
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.database as db_module
from app.db_init import create_all_tables
from app.models import (
    ChatSuggestionHistoryModel,
    DocumentModel,
    SectionModel,
    SummaryModel,
)
from app.services.suggestion_service import SuggestionService, _jaccard_similarity

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

    with patch("app.routers.chat_meta.get_graph_service") as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities
        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-book-1")

    assert len(result.suggestions) == 4
    all_text = " ".join(s.text for s in result.suggestions)
    assert "Ulysses" in all_text


# ---------------------------------------------------------------------------
# (b) Null document_id returns cross-document suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_null_document_id(db_session):
    """Null document_id returns cross-document entity suggestions."""
    shared_entities = ["quantum entanglement", "Schrodinger", "wave function"]

    with patch("app.routers.chat_meta.get_graph_service") as mock_graph:
        mock_graph.return_value.get_cross_document_entities.return_value = shared_entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id=None)

    assert len(result.suggestions) == 4
    all_text = " ".join(s.text for s in result.suggestions)
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

    with patch("app.routers.chat_meta.get_graph_service") as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-tech-1")

    assert len(result.suggestions) == 4
    all_text = " ".join(s.text for s in result.suggestions)
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

    with patch("app.routers.chat_meta.get_graph_service") as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-video-1")

    assert len(result.suggestions) == 4
    all_text = " ".join(s.text for s in result.suggestions)
    assert "neural networks" in all_text or "Hinton" in all_text


# ---------------------------------------------------------------------------
# (e) Empty library returns onboarding suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_empty_library(db_session):
    """No cross-document entities returns onboarding suggestions."""
    with patch("app.routers.chat_meta.get_graph_service") as mock_graph:
        mock_graph.return_value.get_cross_document_entities.return_value = []

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id=None)

    assert len(result.suggestions) == 4
    all_text = " ".join(s.text for s in result.suggestions)
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

    entities = {"CONCEPT": ["one-concept"]}

    with patch("app.routers.chat_meta.get_graph_service") as mock_graph:
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities

        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-sparse-1")

    assert len(result.suggestions) == 4


# ---------------------------------------------------------------------------
# (g) AC11: suggestions not in recent history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_not_in_history(db_session):
    """Returned LLM suggestions must not overlap with recent history texts."""
    doc = _make_doc("doc-hist-1", "History Doc", "book")
    db_session.add(doc)
    # Need executive summary for LLM path to activate
    db_session.add(
        SummaryModel(
            id=str(uuid.uuid4()),
            document_id="doc-hist-1",
            mode="executive",
            content="A story about Alice and curiosity.",
        )
    )
    await db_session.commit()

    # Seed 3 history rows
    for i in range(3):
        db_session.add(
            ChatSuggestionHistoryModel(
                id=str(uuid.uuid4()),
                document_id="doc-hist-1",
                suggestion_text=f"Previously shown question {i}",
                bloom_level=5,
                was_asked=False,
                shown_at=datetime.now(UTC),
            )
        )
    await db_session.commit()

    entities = {"PERSON": ["Alice"], "CONCEPT": ["curiosity"]}

    # Mock LLM to return questions that do NOT overlap with history
    llm_questions = [
        {"question": "What motivates Alice?", "bloom_level": 5},
        {"question": "Explain curiosity in context", "bloom_level": 5},
        {"question": "How does Alice change?", "bloom_level": 5},
        {"question": "Why is curiosity central?", "bloom_level": 5},
        {"question": "Compare Alice early vs late", "bloom_level": 5},
        {"question": "Evaluate Alice decisions", "bloom_level": 5},
    ]
    import json as _json

    mock_llm_response = AsyncMock()
    mock_llm_response.choices = [AsyncMock(message=AsyncMock(content=_json.dumps(llm_questions)))]

    with (
        patch(
            "app.routers.chat_meta.get_graph_service",
        ) as mock_graph,
        patch(
            "app.services.llm.litellm.acompletion",
            return_value=mock_llm_response,
        ),
        patch(
            "app.services.settings_service.get_litellm_kwargs",
            return_value={"model": "test"},
        ),
    ):
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities
        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-hist-1")

    history_texts = {f"Previously shown question {i}" for i in range(3)}
    for item in result.suggestions:
        assert item.text not in history_texts
        assert item.id != ""


# ---------------------------------------------------------------------------
# (h) AC12: bloom level decreases per 4 asked questions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bloom_level_decrease(db_session):
    """Bloom level: starts at 5, decreases by 1 per 4 asked questions, floor at 2."""
    svc = SuggestionService()

    # 0 asked -> level 5
    level = await svc.get_target_bloom_level("doc-bloom-1")
    assert level == 5

    # Seed 4 asked rows
    for i in range(4):
        db_session.add(
            ChatSuggestionHistoryModel(
                id=str(uuid.uuid4()),
                document_id="doc-bloom-1",
                suggestion_text=f"Asked question {i}",
                bloom_level=5,
                was_asked=True,
                shown_at=datetime.now(UTC),
            )
        )
    await db_session.commit()

    level = await svc.get_target_bloom_level("doc-bloom-1")
    assert level == 4

    # Seed 4 more (total 8) -> level 3
    for i in range(4, 8):
        db_session.add(
            ChatSuggestionHistoryModel(
                id=str(uuid.uuid4()),
                document_id="doc-bloom-1",
                suggestion_text=f"Asked question {i}",
                bloom_level=4,
                was_asked=True,
                shown_at=datetime.now(UTC),
            )
        )
    await db_session.commit()

    level = await svc.get_target_bloom_level("doc-bloom-1")
    assert level == 3

    # Seed many more to hit floor
    for i in range(8, 20):
        db_session.add(
            ChatSuggestionHistoryModel(
                id=str(uuid.uuid4()),
                document_id="doc-bloom-1",
                suggestion_text=f"Asked question {i}",
                bloom_level=3,
                was_asked=True,
                shown_at=datetime.now(UTC),
            )
        )
    await db_session.commit()

    level = await svc.get_target_bloom_level("doc-bloom-1")
    assert level == 2


# ---------------------------------------------------------------------------
# (i) AC13: fallback to template when LLM raises ServiceUnavailableError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_on_llm_unavailable(db_session):
    """When LLM raises ServiceUnavailableError, fallback to S187 templates."""
    import litellm as litellm_mod

    doc = _make_doc("doc-fallback-1", "Fallback Book", "book")
    db_session.add(doc)
    db_session.add(_make_section("doc-fallback-1", "Chapter One", 1))
    # Seed executive summary so the LLM path is entered
    db_session.add(
        SummaryModel(
            id=str(uuid.uuid4()),
            document_id="doc-fallback-1",
            mode="executive",
            content="A tale of a hero and bravery in a kingdom.",
        )
    )
    await db_session.commit()

    entities = {
        "PERSON": ["Hero"],
        "CONCEPT": ["bravery"],
        "PLACE": ["Kingdom"],
    }

    with (
        patch("app.routers.chat_meta.get_graph_service") as mock_graph,
        patch(
            "app.services.llm.litellm.acompletion",
            side_effect=litellm_mod.ServiceUnavailableError(
                message="Service unavailable",
                model="test",
                llm_provider="test",
            ),
        ),
        patch("app.services.settings_service.get_litellm_kwargs", return_value={"model": "test"}),
    ):
        mock_graph.return_value.get_entities_by_type_for_document.return_value = entities
        from app.routers.chat_meta import get_suggestions

        result = await get_suggestions(document_id="doc-fallback-1")

    # Should still get 4 template-based suggestions
    assert len(result.suggestions) == 4
    all_text = " ".join(s.text for s in result.suggestions)
    assert "Hero" in all_text


# ---------------------------------------------------------------------------
# (j) AC14: Jaccard > 0.7 filtered out
# ---------------------------------------------------------------------------


def test_jaccard_filter():
    """Near-duplicate suggestion with Jaccard > 0.7 is filtered out."""
    # Identical strings -> Jaccard 1.0
    assert _jaccard_similarity("what motivates the hero", "what motivates the hero") == 1.0
    # Very similar
    sim = _jaccard_similarity(
        "what motivates the hero throughout the story",
        "what motivates the hero throughout the narrative",
    )
    assert sim > 0.7

    # Different strings -> low similarity
    sim_low = _jaccard_similarity(
        "what motivates the hero",
        "explain the economic policy of the kingdom",
    )
    assert sim_low < 0.3

    # Integration: filter_near_duplicates removes high-similarity candidates
    svc = SuggestionService()
    candidates = [
        {"question": "what motivates the hero throughout the story", "bloom_level": 5},
        {"question": "explain the economic system", "bloom_level": 5},
    ]
    history = ["what motivates the hero throughout the narrative"]
    filtered = svc.filter_near_duplicates(candidates, history, threshold=0.7)
    assert len(filtered) == 1
    assert filtered[0]["question"] == "explain the economic system"
