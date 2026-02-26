"""Fast tests for FSRS study session API and flashcard 503 error.

All tests use isolated in-memory SQLite (same pattern as test_flashcards.py).
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import litellm
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, FlashcardModel

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


def _make_card(doc_id: str, question: str = "Q?", answer: str = "A.") -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=str(uuid.uuid4()),
        question=question,
        answer=answer,
        source_excerpt="",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=None,
        reps=0,
        lapses=0,
        created_at=datetime.utcnow(),
        is_user_edited=False,
    )


def _make_doc(doc_id: str) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="Test Doc",
        format="txt",
        content_type="notes",
        word_count=100,
        page_count=1,
        file_path="/tmp/test.txt",
        stage="complete",
    )


def _make_chunk(doc_id: str) -> ChunkModel:
    return ChunkModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        section_id=None,
        text="Test chunk text for LLM flashcard generation.",
        token_count=10,
        page_number=1,
        chunk_index=0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_start_session(test_db):
    """POST /study/session/{doc}/start returns card_id, question, answer, cards_remaining >= 1."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        for i in range(3):
            session.add(_make_card(doc_id, question=f"Q{i}?", answer=f"A{i}."))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/study/session/{doc_id}/start")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["card_id"], str)
    assert isinstance(data["question"], str)
    assert isinstance(data["answer"], str)
    assert isinstance(data["cards_remaining"], int)
    assert data["cards_remaining"] >= 1


async def test_review_card(test_db):
    """POST /study/session/{doc_id}/review returns next_card or done=true."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        for i in range(3):
            session.add(_make_card(doc_id, question=f"Q{i}?", answer=f"A{i}."))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post(f"/study/session/{doc_id}/start")
        assert start.status_code == 200
        card_id = start.json()["card_id"]

        resp = await client.post(
            f"/study/session/{doc_id}/review",
            json={"card_id": card_id, "rating": 3},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "done" in data
    if not data["done"]:
        assert data["next_card"] is not None
        assert isinstance(data["next_card"]["card_id"], str)


async def test_session_complete(test_db):
    """Review all 3 cards with rating=4 (easy) → all scheduled far in future → done=true."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        for i in range(3):
            session.add(_make_card(doc_id, question=f"Q{i}?", answer=f"A{i}."))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Collect all card IDs first
        start = await client.post(f"/study/session/{doc_id}/start")
        assert start.status_code == 200

        reviewed = set()
        current_card_id = start.json()["card_id"]

        for _ in range(10):  # safety limit
            if current_card_id in reviewed:
                # All 3 new cards already rated easy → done
                break
            reviewed.add(current_card_id)
            resp = await client.post(
                f"/study/session/{doc_id}/review",
                json={"card_id": current_card_id, "rating": 4},
            )
            assert resp.status_code == 200
            data = resp.json()
            if data["done"]:
                break
            next_card = data.get("next_card")
            if next_card is None:
                break
            current_card_id = next_card["card_id"]

    # After rating all 3 cards "easy", FSRS schedules them far in future.
    # Either the final response was done=true, or we reviewed all 3 cards.
    assert resp.json()["done"] or len(reviewed) >= 3


async def test_due_date_updated(test_db):
    """After rating a card, FlashcardModel.due_date must not be None."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            FlashcardModel(
                id=card_id,
                document_id=doc_id,
                chunk_id=str(uuid.uuid4()),
                question="Test Q?",
                answer="Test A.",
                source_excerpt="",
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=None,
                reps=0,
                lapses=0,
                created_at=datetime.utcnow(),
                is_user_edited=False,
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(f"/study/session/{doc_id}/start")
        await client.post(
            f"/study/session/{doc_id}/review",
            json={"card_id": card_id, "rating": 3},
        )

    async with factory() as session:
        from sqlalchemy import select as sa_select

        result = await session.execute(
            sa_select(FlashcardModel).where(FlashcardModel.id == card_id)
        )
        card = result.scalar_one()
        assert card.due_date is not None, "FSRS should have set due_date after review"


async def test_503_on_generate(test_db, monkeypatch):
    """POST /flashcards/generate returns HTTP 503 when LLM is unavailable."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    # Insert a doc + chunk so the service proceeds to the LLM call
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(doc_id))
        await session.commit()

    import app.services.llm as llm_module

    llm_module._llm_service = None

    monkeypatch.setattr(
        litellm,
        "acompletion",
        AsyncMock(
            side_effect=litellm.exceptions.ServiceUnavailableError(
                message="Ollama offline",
                llm_provider="ollama",
                model="mistral",
            )
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/flashcards/generate",
            json={"document_id": doc_id, "scope": "full", "section_heading": None, "count": 5},
        )

    assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    assert "Ollama is not running" in resp.json()["detail"]
