"""Tests for graph-driven flashcard generation (S112).

Covers FlashcardService.generate_from_graph() and the two new endpoints:
  GET  /flashcards/entity-pairs
  POST /flashcards/generate-from-graph
"""

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from stubs import MockLLMService as _MockLLMService

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel
from app.services.flashcard import FlashcardService
from app.types import ScoredChunk

# ---------------------------------------------------------------------------
# Isolated test DB fixture
# ---------------------------------------------------------------------------


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


def _make_doc(doc_id: str | None = None, **kwargs) -> DocumentModel:
    defaults = {
        "id": doc_id or str(uuid.uuid4()),
        "title": "Test Doc",
        "format": "txt",
        "content_type": "notes",
        "word_count": 100,
        "page_count": 1,
        "file_path": "/tmp/test.txt",
        "stage": "complete",
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


def _make_chunk(chunk_id: str | None = None, doc_id: str = "doc-1", **kwargs) -> ChunkModel:
    defaults = {
        "id": chunk_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "section_id": None,
        "text": "The Time Traveller met Weena in the future.",
        "token_count": 9,
        "page_number": 1,
        "chunk_index": 0,
    }
    defaults.update(kwargs)
    return ChunkModel(**defaults)


def _make_scored_chunk(chunk_id: str, doc_id: str) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id=doc_id,
        text="The Time Traveller met Weena in the future.",
        section_heading="",
        page=1,
        score=0.9,
        source="vector",
    )


# ---------------------------------------------------------------------------
# Deterministic graph service stubs
# ---------------------------------------------------------------------------


class _GraphWithPairs:
    """Returns one RELATED_TO pair for any document."""

    def get_related_entity_pairs_for_document(self, doc_id: str, limit: int = 5):
        return [("Time Traveller", "Weena", "rescues", 0.9)]

    def get_co_occurring_pairs_for_document(self, doc_id: str, limit: int = 5):
        return []


class _GraphWithCoOccurs:
    """No RELATED_TO pairs; returns one CO_OCCURS pair instead."""

    def get_related_entity_pairs_for_document(self, doc_id: str, limit: int = 5):
        return []

    def get_co_occurring_pairs_for_document(self, doc_id: str, limit: int = 5):
        return [("Eloi", "Morlock", 12)]


class _GraphEmpty:
    """Returns no pairs at all."""

    def get_related_entity_pairs_for_document(self, doc_id: str, limit: int = 5):
        return []

    def get_co_occurring_pairs_for_document(self, doc_id: str, limit: int = 5):
        return []


class _Retriever:
    """Returns one ScoredChunk for any query."""

    def __init__(self, chunk_id: str, doc_id: str):
        self._chunk = _make_scored_chunk(chunk_id, doc_id)

    async def retrieve(self, query: str, document_ids: list, k: int = 5):
        return [self._chunk]


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


async def test_generate_from_graph_creates_cards_for_related_pair(test_db):
    """generate_from_graph() creates cards with source='graph' for RELATED_TO pairs."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps([
        {
            "question": "How does Time Traveller relate to Weena?",
            "answer": "The Time Traveller rescues Weena from drowning.",
            "source_excerpt": "The Time Traveller met Weena.",
        }
    ])
    mock_llm = _MockLLMService(response=llm_json)

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        patch("app.services.graph.get_graph_service", return_value=_GraphWithPairs()),
        patch("app.services.retriever.get_retriever", return_value=_Retriever(chunk_id, doc_id)),
    ):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_from_graph(
                document_id=doc_id, k=5, session=session
            )

    assert len(cards) == 1
    assert cards[0].source == "graph"
    assert cards[0].deck == "graph"
    assert cards[0].fsrs_state == "new"
    assert cards[0].reps == 0


async def test_generate_from_graph_returns_empty_when_no_pairs(test_db):
    """generate_from_graph() returns [] without calling LLM when graph has no pairs."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    mock_llm = _MockLLMService()

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        patch("app.services.graph.get_graph_service", return_value=_GraphEmpty()),
    ):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_from_graph(
                document_id=doc_id, k=5, session=session
            )

    assert cards == []
    assert mock_llm.call_count == 0


async def test_generate_from_graph_uses_co_occurs_fallback(test_db):
    """generate_from_graph() falls back to CO_OCCURS edges when RELATED_TO is empty."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps([
        {
            "question": "What connects Eloi and Morlock?",
            "answer": "They co-exist in the far future.",
            "source_excerpt": "Eloi and Morlock.",
        }
    ])
    mock_llm = _MockLLMService(response=llm_json)

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        patch("app.services.graph.get_graph_service", return_value=_GraphWithCoOccurs()),
        patch("app.services.retriever.get_retriever", return_value=_Retriever(chunk_id, doc_id)),
    ):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_from_graph(
                document_id=doc_id, k=5, session=session
            )

    assert len(cards) == 1
    assert cards[0].source == "graph"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


async def test_post_generate_from_graph_returns_201(test_db):
    """POST /flashcards/generate-from-graph returns 201 with a list payload."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps([
        {
            "question": "How does Time Traveller relate to Weena?",
            "answer": "He rescues her.",
            "source_excerpt": "Met Weena.",
        }
    ])
    mock_llm = _MockLLMService(response=llm_json)

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        patch("app.services.graph.get_graph_service", return_value=_GraphWithPairs()),
        patch("app.services.retriever.get_retriever", return_value=_Retriever(chunk_id, doc_id)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/flashcards/generate-from-graph",
                json={"document_id": doc_id, "k": 3},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["source"] == "graph"


async def test_get_entity_pairs_returns_200_with_pairs_key(test_db):
    """GET /flashcards/entity-pairs returns 200 with {pairs: [...]} shape."""
    _, _factory, _ = test_db

    with patch("app.services.graph.get_graph_service", return_value=_GraphWithPairs()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/flashcards/entity-pairs",
                params={"document_id": "any-doc-id"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "pairs" in data
    pairs = data["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["name_a"] == "Time Traveller"
    assert pairs[0]["name_b"] == "Weena"
    assert pairs[0]["relation_label"] == "rescues"
    assert 0.0 <= pairs[0]["confidence"] <= 1.0


async def test_get_entity_pairs_co_occurs_confidence_is_normalised(test_db):
    """GET /flashcards/entity-pairs normalises CO_OCCURS weights to [0.0, 1.0]."""
    _, _factory, _ = test_db

    with patch("app.services.graph.get_graph_service", return_value=_GraphWithCoOccurs()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/flashcards/entity-pairs",
                params={"document_id": "any-doc-id"},
            )

    assert resp.status_code == 200
    data = resp.json()
    pairs = data["pairs"]
    assert len(pairs) == 1
    # Raw CO_OCCURS weight was 12 -- must be normalised, not returned as-is
    assert 0.0 <= pairs[0]["confidence"] <= 1.0
    # The top pair normalises to 1.0 (it is the max)
    assert pairs[0]["confidence"] == pytest.approx(1.0)
    assert pairs[0]["relation_label"] == "co-occurs"
