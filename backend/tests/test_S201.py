"""Tests for S201: Tag auto-save normalization, duplicate note dedup, and
clustering normalization.

Three AC-driven unit/integration tests:
  1. suggest_tags returns normalized tag slugs
  2. duplicate note creation within 5s window returns existing note
  3. batch_accept_suggestions stores lower-case collection names
"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ClusterSuggestionModel, NoteModel

# Fixture


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


# AC9: suggest_tags returns normalized tag slugs


@pytest.mark.asyncio
async def test_suggest_tags_returns_normalized_slugs(test_db):
    """POST /notes/{id}/suggest-tags returns tags normalized via normalize_tag_slug."""
    engine, factory, _ = test_db

    # Seed a note
    note_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            NoteModel(
                id=note_id,
                content="Some content about Machine Learning and Biology",
                tags=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    # Mock the note tagger to return un-normalized tags
    mock_tagger = AsyncMock()
    mock_tagger.suggest_tags = AsyncMock(
        return_value=["Machine Learning", "Science/Cell_Division", "Deep Learning"]
    )

    with patch("app.services.note_tagger.get_note_tagger", return_value=mock_tagger):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(f"/notes/{note_id}/suggest-tags")

    assert resp.status_code == 200
    data = resp.json()
    tags = data["tags"]
    assert "machine-learning" in tags
    assert "science/cell-division" in tags
    assert "deep-learning" in tags
    # Ensure no un-normalized originals leak through
    assert "Machine Learning" not in tags
    assert "Science/Cell_Division" not in tags


@pytest.mark.unstable  # POST /notes schedules a real embed/graph task, like the dedup test above
@pytest.mark.asyncio
async def test_create_note_returns_before_tagger_resolves(test_db):
    """POST /notes must not await the tagger inline (regression).

    `create_note` used to await `suggest_tags()` before responding, so a busy
    LLM -- e.g. a background ingestion job holding the only model slot --
    hung every note save, and the "Open full note" navigation gated on that
    save, for as long as the queue was busy. A tagger that never resolves
    must not stop the request from completing; tagging happens in the
    background instead (`auto_tag_and_store_note`).
    """
    from app.services import note_tagger as tagger_module
    from app.services.notes_service import auto_tag_and_store_note

    never_resolves: asyncio.Future = asyncio.get_event_loop().create_future()

    class HangingTagger:
        async def suggest_tags(self, content: str) -> list[str]:
            return await never_resolves  # never completes during this test

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch.object(tagger_module, "get_note_tagger", return_value=HangingTagger()):
            resp = await asyncio.wait_for(
                client.post(
                    "/notes",
                    json={
                        "content": "Some content long enough to trigger tagging.",
                        "tags": [],
                        "document_id": None,
                    },
                ),
                timeout=2.0,
            )
        note_id = resp.json()["id"]
        never_resolves.cancel()  # unwind the still-pending background task

        assert resp.status_code == 201
        assert resp.json()["tags"] == []

        # The background helper itself still tags the note once the model answers.
        mock_tagger = AsyncMock()
        mock_tagger.suggest_tags = AsyncMock(return_value=["Reinforcement Learning"])
        with patch.object(tagger_module, "get_note_tagger", return_value=mock_tagger):
            await auto_tag_and_store_note(note_id, "Some content long enough to trigger tagging.")

        reread = (await client.get(f"/notes/{note_id}")).json()
    assert reread["tags"] == ["reinforcement-learning"]


# AC10: duplicate note creation within 5s window returns existing note


@pytest.mark.unstable
@pytest.mark.asyncio
async def test_duplicate_note_dedup_within_5s(test_db):
    """POST /notes with identical (document_id, section_id, content) within 5s returns existing."""
    engine, factory, _ = test_db

    payload = {
        "document_id": "doc-1",
        "section_id": "sec-1",
        "content": "This is a test note for dedup.",
        "tags": [],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # First create
        resp1 = await client.post("/notes", json=payload)
        assert resp1.status_code == 201
        note1 = resp1.json()

        # Second create (duplicate) -- should return the same note
        resp2 = await client.post("/notes", json=payload)
        # Dedup returns 201 status (router decorator) but same note ID
        assert resp2.status_code == 201
        note2 = resp2.json()

    assert note1["id"] == note2["id"], "Duplicate note should return existing note"


# AC11: batch_accept_suggestions stores UPPER-CASE collection names


@pytest.mark.asyncio
async def test_batch_accept_normalizes_collection_names(test_db):
    """batch_accept_suggestions applies normalize_collection_name to UPPER-CASE."""
    engine, factory, _ = test_db

    suggestion_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())

    async with factory() as session:
        # Seed a note so the member insert doesn't violate anything
        session.add(
            NoteModel(
                id=note_id,
                content="Test note",
                tags=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        # Seed a cluster suggestion with a raw (un-normalized) name
        session.add(
            ClusterSuggestionModel(
                id=suggestion_id,
                suggested_name="machine learning notes",
                note_ids=[note_id],
                confidence_score=0.85,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    from app.services.clustering_service import get_clustering_service

    service = get_clustering_service()

    async with factory() as session:
        result_ids = await service.batch_accept_suggestions(
            [{"suggestion_id": suggestion_id}],
            session,
        )

    assert len(result_ids) == 1

    # Verify the collection name is UPPER-CASE normalized
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT name FROM collections WHERE id = :cid"),
                {"cid": result_ids[0]},
            )
        ).fetchone()

    assert row is not None
    assert row[0] == "MACHINE-LEARNING-NOTES"
