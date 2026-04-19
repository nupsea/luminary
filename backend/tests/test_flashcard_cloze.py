"""Tests for S154: cloze deletion flashcard generation."""

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
from app.models import ChunkModel, DocumentModel, SectionModel
from app.services.flashcard import (
    FlashcardService,
    _build_cloze_question,
    _parse_cloze_text,
)

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


def _make_chunk(
    chunk_id: str | None = None,
    doc_id: str = "doc-1",
    section_id: str | None = None,
    **kwargs,
) -> ChunkModel:
    defaults = {
        "id": chunk_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "section_id": section_id,
        "text": "A generator function uses yield instead of return to produce values lazily.",
        "token_count": 15,
        "page_number": 1,
        "chunk_index": 0,
    }
    defaults.update(kwargs)
    return ChunkModel(**defaults)


def _make_section(section_id: str, doc_id: str, heading: str = "Generators") -> SectionModel:
    return SectionModel(
        id=section_id,
        document_id=doc_id,
        heading=heading,
        level=1,
        page_start=0,
        page_end=1,
        section_order=0,
        preview="x" * 250,
    )


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_parse_cloze_text_extracts_blanks():
    """_parse_cloze_text returns terms in order from {{term}} markers."""
    result = _parse_cloze_text("A {{generator}} uses {{yield}}")
    assert result == ["generator", "yield"]


def test_parse_cloze_text_no_blanks():
    """_parse_cloze_text returns empty list when no markers present."""
    result = _parse_cloze_text("No blanks here")
    assert result == []


def test_build_cloze_question_replaces_markers():
    """_build_cloze_question replaces {{term}} with [____]."""
    result = _build_cloze_question("A {{generator}} uses {{yield}}")
    assert result == "A [____] uses [____]"


def test_build_cloze_question_no_markers():
    """_build_cloze_question returns original text when no markers present."""
    result = _build_cloze_question("plain text")
    assert result == "plain text"


# ---------------------------------------------------------------------------
# Service tests (mocked LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_cloze_valid(test_db):
    """generate_cloze creates a card with correct cloze_text and question fields."""
    _, factory, _ = test_db
    doc_id = "doc-cloze-1"
    sec_id = "sec-cloze-1"
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(sec_id, doc_id))
        session.add(_make_chunk(doc_id=doc_id, section_id=sec_id))
        await session.commit()

    valid_response = (
        '[{"cloze_text": "A {{generator}} uses {{yield}}", "source_excerpt": "A generator..."}]'
    )
    mock_llm = _MockLLMService(response=valid_response)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_cloze(sec_id, count=5, session=session)

    assert len(cards) == 1
    card = cards[0]
    assert card.cloze_text == "A {{generator}} uses {{yield}}"
    assert card.question == "A [____] uses [____]"
    assert card.flashcard_type == "cloze"
    assert "generator" in card.answer
    assert "yield" in card.answer
    assert mock_llm.call_count == 1


@pytest.mark.asyncio
async def test_generate_cloze_malformed_triggers_retry(test_db):
    """generate_cloze retries once on malformed response; both malformed => 0 cards."""
    _, factory, _ = test_db
    doc_id = "doc-cloze-2"
    sec_id = "sec-cloze-2"
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(sec_id, doc_id, heading="Decorators"))
        session.add(_make_chunk(doc_id=doc_id, section_id=sec_id))
        await session.commit()

    # Response has no {{}} markers -- malformed on both attempts
    malformed = '[{"cloze_text": "no blanks here", "source_excerpt": "x"}]'
    mock_llm = _MockLLMService(response=malformed)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_cloze(sec_id, count=3, session=session)

    assert cards == []
    assert mock_llm.call_count == 2  # first attempt + one retry


@pytest.mark.asyncio
async def test_generate_cloze_returns_empty_for_unknown_section(test_db):
    """generate_cloze returns [] when section has no chunks."""
    _, factory, _ = test_db
    mock_llm = _MockLLMService()

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_cloze("nonexistent-section", count=5, session=session)

    assert cards == []
    assert mock_llm.call_count == 0


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloze_endpoint_returns_201(test_db):
    """POST /flashcards/cloze/{section_id} returns 201 with created cards."""
    _, factory, _ = test_db
    doc_id = "doc-ep"
    sec_id = "sec-ep"
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(sec_id, doc_id, heading="Test Section"))
        session.add(_make_chunk(doc_id=doc_id, section_id=sec_id))
        await session.commit()

    valid_cloze = '[{"cloze_text": "Python uses {{indentation}}", "source_excerpt": "..."}]'
    mock_llm = _MockLLMService(response=valid_cloze)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/flashcards/cloze/{sec_id}?count=3")

    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["flashcard_type"] == "cloze"
    assert data[0]["cloze_text"] == "Python uses {{indentation}}"
    assert data[0]["question"] == "Python uses [____]"
