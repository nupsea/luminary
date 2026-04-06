"""Tests for S206: flashcard search FTS5 fixes -- backfill, sanitization, LIKE fallback."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel
from app.services.flashcard import _sanitize_fts5_query, _sync_flashcard_fts

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


def _make_flashcard(
    card_id: str | None = None,
    doc_id: str = "doc-1",
    question: str = "What is entanglement?",
    answer: str = "A quantum correlation between particles.",
    **kwargs,
) -> FlashcardModel:
    now = datetime.now(UTC)
    defaults = {
        "id": card_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "chunk_id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "source_excerpt": "Some excerpt.",
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
# AC1: keyword in question returns flashcard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_keyword_in_question(test_db):
    """Searching for a keyword in the question returns that flashcard."""
    _, factory, _ = test_db

    card = _make_flashcard(
        question="What is photosynthesis?",
        answer="The process by which plants convert sunlight.",
    )
    async with factory() as session:
        session.add(card)
        await _sync_flashcard_fts(card, session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/flashcards/search", params={"query": "photosynthesis"})
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert card.id in ids


# ---------------------------------------------------------------------------
# AC2: keyword in answer returns flashcard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_keyword_in_answer(test_db):
    """Searching for a keyword in the answer returns that flashcard."""
    _, factory, _ = test_db

    card = _make_flashcard(
        question="Describe the water cycle.",
        answer="Evaporation, condensation, precipitation, and collection.",
    )
    async with factory() as session:
        session.add(card)
        await _sync_flashcard_fts(card, session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/flashcards/search", params={"query": "evaporation"})
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert card.id in ids


# ---------------------------------------------------------------------------
# AC3: multi-word search with AND semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_multiword_and_semantics(test_db):
    """Multi-word search returns cards matching all terms."""
    _, factory, _ = test_db

    card_both = _make_flashcard(
        question="What is quantum entanglement?",
        answer="A quantum correlation between distant particles.",
    )
    card_partial = _make_flashcard(
        question="What is classical mechanics?",
        answer="Study of motion and particles.",
    )
    async with factory() as session:
        session.add(card_both)
        session.add(card_partial)
        await _sync_flashcard_fts(card_both, session)
        await _sync_flashcard_fts(card_partial, session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/flashcards/search", params={"query": "quantum particles"})
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert card_both.id in ids
        # card_partial has "particles" in answer but not "quantum" -- should not match FTS AND
        assert card_partial.id not in ids


# ---------------------------------------------------------------------------
# AC7: special characters do not cause FTS5 syntax errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_special_characters_no_error(test_db):
    """Special characters in search query do not raise FTS5 syntax errors."""
    _, _, _ = test_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for q in ['(test)', '"hello"', 'foo:bar', 'a AND b', 'NOT nothing', '{braces}']:
            resp = await client.get("/flashcards/search", params={"query": q})
            assert resp.status_code == 200, f"Failed for query: {q}"


# ---------------------------------------------------------------------------
# AC4: newly created flashcards immediately searchable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_newly_created_card_searchable(test_db):
    """When a card is created via sync helper, it is immediately searchable."""
    _, factory, _ = test_db

    card = _make_flashcard(
        question="What is mitochondria?",
        answer="The powerhouse of the cell.",
    )
    async with factory() as session:
        session.add(card)
        await _sync_flashcard_fts(card, session)
        await session.commit()

        # Verify searchable via MATCH
        match_row = (
            await session.execute(
                text(
                    "SELECT flashcard_id FROM flashcards_fts"
                    " WHERE flashcards_fts MATCH 'mitochondria'"
                )
            )
        ).first()
        assert match_row is not None
        assert match_row[0] == card.id


# ---------------------------------------------------------------------------
# AC5: updated flashcard content reflected in search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updated_card_searchable(test_db):
    """After updating a card, search returns the new content."""
    _, factory, _ = test_db

    card = _make_flashcard(
        question="Old question about gravity",
        answer="Old answer about gravity.",
    )
    async with factory() as session:
        session.add(card)
        await _sync_flashcard_fts(card, session)
        await session.commit()

    # Update the card
    async with factory() as session:
        result = await session.execute(
            text("SELECT id FROM flashcards WHERE id = :cid"), {"cid": card.id}
        )
        assert result.first() is not None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.put(
            f"/flashcards/{card.id}",
            json={"question": "New question about thermodynamics", "answer": "Heat transfer."},
        )
        assert resp.status_code == 200

        # Search old keyword should NOT find it
        resp_old = await client.get("/flashcards/search", params={"query": "gravity"})
        ids_old = [item["id"] for item in resp_old.json()["items"]]
        assert card.id not in ids_old

        # Search new keyword should find it
        resp_new = await client.get("/flashcards/search", params={"query": "thermodynamics"})
        ids_new = [item["id"] for item in resp_new.json()["items"]]
        assert card.id in ids_new


# ---------------------------------------------------------------------------
# AC6: deleted flashcard not in search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_card_not_searchable(test_db):
    """After deleting a card, search does not return it."""
    _, factory, _ = test_db

    card = _make_flashcard(
        question="What is osmosis?",
        answer="Movement of water through a membrane.",
    )
    async with factory() as session:
        session.add(card)
        await _sync_flashcard_fts(card, session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Confirm searchable first
        resp = await client.get("/flashcards/search", params={"query": "osmosis"})
        assert card.id in [item["id"] for item in resp.json()["items"]]

        # Delete
        del_resp = await client.delete(f"/flashcards/{card.id}")
        assert del_resp.status_code == 204

        # Confirm not searchable
        resp2 = await client.get("/flashcards/search", params={"query": "osmosis"})
        assert card.id not in [item["id"] for item in resp2.json()["items"]]


# ---------------------------------------------------------------------------
# Unit: _sanitize_fts5_query
# ---------------------------------------------------------------------------


def test_sanitize_fts5_simple():
    assert _sanitize_fts5_query("hello world") == '"hello" AND "world"'


def test_sanitize_fts5_strips_operators():
    assert _sanitize_fts5_query('hello (world) "test"') == '"hello" AND "world" AND "test"'


def test_sanitize_fts5_removes_boolean_keywords():
    assert _sanitize_fts5_query("cats AND dogs") == '"cats" AND "dogs"'


def test_sanitize_fts5_all_special_returns_empty():
    assert _sanitize_fts5_query("(){}*:^~") == ""


def test_sanitize_fts5_single_word():
    assert _sanitize_fts5_query("mitochondria") == '"mitochondria"'


# ---------------------------------------------------------------------------
# AC9: existing filters work with search query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_with_filter_combination(test_db):
    """Search query + fsrs_state filter returns intersection."""
    _, factory, _ = test_db

    card_new = _make_flashcard(
        question="What is DNA replication?",
        answer="The process of copying DNA.",
        fsrs_state="new",
    )
    card_review = _make_flashcard(
        question="What is DNA transcription?",
        answer="Copying DNA to RNA.",
        fsrs_state="review",
    )
    async with factory() as session:
        session.add(card_new)
        session.add(card_review)
        await _sync_flashcard_fts(card_new, session)
        await _sync_flashcard_fts(card_review, session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/flashcards/search", params={"query": "DNA", "fsrs_state": "new"}
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]
        assert card_new.id in ids
        assert card_review.id not in ids
