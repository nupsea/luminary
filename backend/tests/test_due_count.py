"""Tests for GET /study/due-count endpoint (S118)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """Isolated in-memory SQLite DB for each test."""
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


def _card(due_date: datetime | None = None) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id="doc1",
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
        fsrs_state="review",
        fsrs_stability=1.0,
        fsrs_difficulty=0.5,
        due_date=due_date,
    )


@pytest.mark.asyncio
async def test_due_count_empty_db(test_db):
    """No flashcards -> due_today == 0."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 0


@pytest.mark.asyncio
async def test_due_count_with_due_cards(test_db):
    """Two cards with due_date in the past -> due_today == 2."""
    _, factory, _ = test_db
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(_card(due_date=now - timedelta(days=1)))
        session.add(_card(due_date=now - timedelta(hours=1)))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 2


@pytest.mark.asyncio
async def test_due_count_excludes_future_cards(test_db):
    """Cards with due_date in the future are not counted."""
    _, factory, _ = test_db
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(_card(due_date=now + timedelta(days=7)))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 0


@pytest.mark.asyncio
async def test_due_count_excludes_null_due_date(test_db):
    """Cards with due_date=None (never scheduled) are not counted."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_card(due_date=None))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/due-count")
    assert resp.status_code == 200
    assert resp.json()["due_today"] == 0
