"""Tests for flashcard generation and CRUD endpoints."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from stubs import CapturingLLMService as _CapturingLLMService
from stubs import MockLLMService as _MockLLMService

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, FlashcardModel
from app.services.flashcard import FlashcardService

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
        "text": "Quantum entanglement describes a correlation between particles.",
        "token_count": 12,
        "page_number": 1,
        "chunk_index": 0,
    }
    defaults.update(kwargs)
    return ChunkModel(**defaults)


def _make_flashcard(card_id: str | None = None, doc_id: str = "doc-1", **kwargs) -> FlashcardModel:
    now = datetime.now(UTC)
    defaults = {
        "id": card_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "chunk_id": str(uuid.uuid4()),
        "question": "What is entanglement?",
        "answer": "A quantum correlation between particles.",
        "source_excerpt": "Quantum entanglement describes a correlation.",
        "fsrs_state": "new",
        "fsrs_stability": 0.0,
        "fsrs_difficulty": 0.0,
        "due_date": now,
        "reps": 0,
        "lapses": 0,
        "created_at": now,
    }
    defaults.update(kwargs)
    return FlashcardModel(**defaults)


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


async def test_service_parses_json_and_creates_cards(test_db):
    """FlashcardService.generate() parses LLM JSON output and stores cards."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps([
        {"question": "What is a qubit?", "answer": "A quantum bit.", "source_excerpt": "A qubit."},
        {
            "question": "What is superposition?",
            "answer": "A state of being both 0 and 1.",
            "source_excerpt": "Superposition...",
        },
    ])
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=2,
                session=session,
            )

    assert len(cards) == 2
    assert cards[0].fsrs_state == "new"
    assert cards[0].fsrs_stability == 0.0
    assert cards[0].reps == 0
    assert cards[0].due_date is not None
    assert cards[0].question == "What is a qubit?"
    assert cards[1].answer == "A state of being both 0 and 1."


async def test_service_strips_markdown_fences(test_db):
    """FlashcardService.generate() handles LLM responses wrapped in markdown fences."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = (
        "```json\n"
        '[{"question": "Q1?", "answer": "A1.", "source_excerpt": "src."}]\n'
        "```"
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert len(cards) == 1
    assert cards[0].question == "Q1?"


async def test_service_returns_empty_when_no_chunks(test_db):
    """FlashcardService.generate() returns [] when document has no chunks."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    mock_llm = _MockLLMService()

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=5,
                session=session,
            )

    assert cards == []
    assert mock_llm.call_count == 0


async def test_service_prompt_includes_count(test_db):
    """LLM prompt includes the requested count."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    mock_llm = _CapturingLLMService(response='[]')

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            await svc.generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=7,
                session=session,
            )

    assert mock_llm.captured_prompts, "LLM generate should have been called"
    assert "7" in mock_llm.captured_prompts[0]


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------


async def test_generate_endpoint_returns_201(test_db):
    """POST /flashcards/generate returns 201 with card list."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps([
        {"question": "Q?", "answer": "A.", "source_excerpt": "src."},
    ])
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/flashcards/generate",
                json={"document_id": doc_id, "scope": "full", "count": 1},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["fsrs_state"] == "new"
    assert data[0]["question"] == "Q?"
    assert data[0]["is_user_edited"] is False


async def test_list_flashcards_returns_all_for_document(test_db):
    """GET /flashcards/{document_id} returns all cards for that document."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_flashcard(doc_id=doc_id, question="Q1?"))
        session.add(_make_flashcard(doc_id=doc_id, question="Q2?"))
        session.add(_make_flashcard(doc_id="other-doc", question="Q3?"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    questions = {c["question"] for c in data}
    assert "Q1?" in questions
    assert "Q2?" in questions
    assert all(c["document_id"] == doc_id for c in data)


async def test_update_flashcard_sets_user_edited(test_db):
    """PUT /flashcards/{id} updates fields and sets is_user_edited=True."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_flashcard(card_id=card_id, doc_id=doc_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/flashcards/{card_id}",
            json={"question": "Updated Q?", "answer": "Updated A."},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["question"] == "Updated Q?"
    assert data["answer"] == "Updated A."
    assert data["is_user_edited"] is True


async def test_update_nonexistent_flashcard_returns_404(test_db):
    """PUT /flashcards/{id} for missing card returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/flashcards/no-such-id", json={"question": "x"})
    assert resp.status_code == 404


async def test_delete_flashcard_returns_204(test_db):
    """DELETE /flashcards/{id} removes the card and returns 204."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_flashcard(card_id=card_id, doc_id=doc_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        del_resp = await client.delete(f"/flashcards/{card_id}")
        assert del_resp.status_code == 204

        list_resp = await client.get(f"/flashcards/{doc_id}")
        ids = [c["id"] for c in list_resp.json()]
        assert card_id not in ids


async def test_delete_nonexistent_flashcard_returns_404(test_db):
    """DELETE /flashcards/{id} for missing card returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/flashcards/no-such-id")
    assert resp.status_code == 404


async def test_export_csv_returns_valid_csv(test_db):
    """GET /flashcards/{document_id}/export/csv returns a valid CSV file."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, title="My Study Guide"))
        session.add(
            _make_flashcard(
                doc_id=doc_id,
                question="What is a qubit?",
                answer="A quantum bit.",
                source_excerpt="A qubit is the basic unit.",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{doc_id}/export/csv")

    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "attachment" in resp.headers.get("content-disposition", "")
    text = resp.text
    assert "question" in text
    assert "What is a qubit?" in text
    assert "My Study Guide" in text


# ---------------------------------------------------------------------------
# S73 — Smart question generation prompt tests
# ---------------------------------------------------------------------------


def test_flashcard_prompt_contains_taxonomy():
    """FLASHCARD_SYSTEM must include comprehension and application quality guidance."""
    from app.services.flashcard import FLASHCARD_SYSTEM

    assert "comprehension" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'comprehension'"
    assert "application" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'application'"


def test_flashcard_prompt_forbids_hypothetical():
    """FLASHCARD_SYSTEM must include AVOID block listing hypothetical questions."""
    from app.services.flashcard import FLASHCARD_SYSTEM

    assert "AVOID" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'AVOID'"
    assert "hypothetical" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'hypothetical'"
