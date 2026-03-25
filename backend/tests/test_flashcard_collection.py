"""Tests for S169: collection-based flashcard generation and GET /flashcards/decks."""

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    FlashcardModel,
    NoteCollectionMemberModel,
    NoteCollectionModel,
    NoteModel,
)
from app.services.flashcard import FlashcardService

# ---------------------------------------------------------------------------
# Fixture
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

    yield factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _content_hash(content: str) -> str:
    return hashlib.sha256(content[:500].encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_from_collection_skips_matching_hash(test_db):
    """Notes already covered by matching source_content_hash are skipped."""
    async with test_db() as session:
        coll_id = str(uuid.uuid4())
        note_id = str(uuid.uuid4())
        content = "This is a test note about Python."

        session.add(NoteCollectionModel(
            id=coll_id,
            name="MyCollection",
            color="#6366F1",
            sort_order=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        session.add(NoteModel(
            id=note_id,
            content=content,
            tags="[]",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        session.add(NoteCollectionMemberModel(
            id=str(uuid.uuid4()),
            note_id=note_id,
            collection_id=coll_id,
            added_at=datetime.now(UTC),
        ))
        # Seed existing flashcard with matching hash
        session.add(FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=None,
            chunk_id=None,
            source="note",
            deck="MyCollection",
            source_content_hash=_content_hash(content),
            question="Q?",
            answer="A.",
            source_excerpt="excerpt",
            difficulty="medium",
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=datetime.now(UTC),
            reps=0,
            lapses=0,
            created_at=datetime.now(UTC),
        ))
        await session.commit()

    async with test_db() as session:
        svc = FlashcardService()
        result = await svc.generate_from_collection(
            collection_id=coll_id,
            count_per_note=3,
            difficulty="medium",
            session=session,
        )

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert result["deck"] == "MyCollection"


@pytest.mark.asyncio
async def test_generate_from_collection_processes_changed_content(test_db):
    """Notes whose stored hash differs from current content are processed."""
    async with test_db() as session:
        coll_id = str(uuid.uuid4())
        note_id = str(uuid.uuid4())
        content = "This is a test note about Python."

        session.add(NoteCollectionModel(
            id=coll_id,
            name="ChangedCollection",
            color="#6366F1",
            sort_order=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        session.add(NoteModel(
            id=note_id,
            content=content,
            tags="[]",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        session.add(NoteCollectionMemberModel(
            id=str(uuid.uuid4()),
            note_id=note_id,
            collection_id=coll_id,
            added_at=datetime.now(UTC),
        ))
        # Seed flashcard with DIFFERENT hash (simulates stale content)
        session.add(FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=None,
            chunk_id=None,
            source="note",
            deck="ChangedCollection",
            source_content_hash="stalehashabcd",
            question="Old Q?",
            answer="Old A.",
            source_excerpt="excerpt",
            difficulty="medium",
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=datetime.now(UTC),
            reps=0,
            lapses=0,
            created_at=datetime.now(UTC),
        ))
        await session.commit()

    import json as _json

    fake_cards = [{"question": "New Q?", "answer": "New A.", "source_excerpt": "ex"}]
    llm_patch = "app.services.llm.LLMService.generate"

    async with test_db() as session:
        svc = FlashcardService()
        with patch(llm_patch, new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _json.dumps(fake_cards)
            result = await svc.generate_from_collection(
                collection_id=coll_id,
                count_per_note=3,
                difficulty="medium",
                session=session,
            )

    assert result["created"] >= 1
    assert result["skipped"] == 0
    assert result["deck"] == "ChangedCollection"


@pytest.mark.asyncio
async def test_get_flashcard_decks_collection_source_type(test_db):
    """GET /flashcards/decks returns source_type='collection' for collection-named deck."""
    async with test_db() as session:
        coll_id = str(uuid.uuid4())
        session.add(NoteCollectionModel(
            id=coll_id,
            name="MyDeck",
            color="#6366F1",
            sort_order=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        session.add(FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=None,
            chunk_id=None,
            source="note",
            deck="MyDeck",
            source_content_hash=None,
            question="Q?",
            answer="A.",
            source_excerpt="excerpt",
            difficulty="medium",
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=datetime.now(UTC),
            reps=0,
            lapses=0,
            created_at=datetime.now(UTC),
        ))
        await session.commit()

    client = TestClient(app)
    resp = client.get("/flashcards/decks")
    assert resp.status_code == 200
    decks = resp.json()
    my_deck = next((d for d in decks if d["deck"] == "MyDeck"), None)
    assert my_deck is not None
    assert my_deck["source_type"] == "collection"
    assert my_deck["collection_id"] == coll_id


@pytest.mark.asyncio
async def test_generate_422_both_collection_id_and_note_ids(test_db):
    """POST /notes/flashcards/generate returns 422 when both collection_id and note_ids given."""
    client = TestClient(app)
    resp = client.post(
        "/notes/flashcards/generate",
        json={
            "collection_id": str(uuid.uuid4()),
            "note_ids": [str(uuid.uuid4())],
        },
    )
    assert resp.status_code == 422
