"""Tests for mastery_pct aggregate on GET /documents list items."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FlashcardModel, PredictionEventModel


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

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _doc(doc_id: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Mastery Test Doc",
        format="txt",
        content_type="book",
        word_count=500,
        page_count=10,
        file_path="/tmp/mastery_test.txt",
        stage="complete",
    )


def _card(doc_id: str, stability: float, bloom: int | None) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        question="q",
        answer="a",
        source_excerpt="src",
        fsrs_stability=stability,
        bloom_level=bloom,
    )


async def _fetch_item(doc_id: str) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        if item["id"] == doc_id:
            return item
    raise AssertionError(f"doc {doc_id} not in response")


@pytest.mark.asyncio
async def test_mastery_pct_none_when_no_flashcards(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_doc(doc_id))
        await session.commit()

    item = await _fetch_item(doc_id)
    assert item["mastery_pct"] is None


@pytest.mark.asyncio
async def test_mastery_pct_weighted_mean_mixed_bloom(test_db):
    """stability=21 with bloom=5 (weight 1.5) + stability=0 with bloom=2 (weight 1.0).
    Expected: (1.0*1.5 + 0.0*1.0) / (1.5 + 1.0) = 0.6 -> 60.0 pct."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_doc(doc_id))
        session.add(_card(doc_id, stability=21.0, bloom=5))
        session.add(_card(doc_id, stability=0.0, bloom=2))
        await session.commit()

    item = await _fetch_item(doc_id)
    assert item["mastery_pct"] == pytest.approx(60.0, abs=0.1)


@pytest.mark.asyncio
async def test_mastery_pct_caps_stability_at_full(test_db):
    """stability=42 (over the 21-day cap) should clamp to 1.0, not 2.0."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_doc(doc_id))
        session.add(_card(doc_id, stability=42.0, bloom=3))
        await session.commit()

    item = await _fetch_item(doc_id)
    assert item["mastery_pct"] == pytest.approx(100.0, abs=0.1)


@pytest.mark.asyncio
async def test_mastery_pct_prediction_error_penalty(test_db):
    """One full-stability card (mean=1.0) + 2 prediction errors -> 1.0 - 0.10 = 0.90."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_doc(doc_id))
        session.add(_card(doc_id, stability=21.0, bloom=3))
        for _ in range(2):
            session.add(
                PredictionEventModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    code_content="x",
                    expected="x",
                    actual="y",
                    correct=False,
                )
            )
        await session.commit()

    item = await _fetch_item(doc_id)
    assert item["mastery_pct"] == pytest.approx(90.0, abs=0.1)


@pytest.mark.asyncio
async def test_mastery_pct_penalty_capped_and_floored(test_db):
    """Many prediction errors get capped at 0.20 penalty; mastery never goes below 0."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_doc(doc_id))
        session.add(_card(doc_id, stability=0.0, bloom=2))
        for _ in range(100):
            session.add(
                PredictionEventModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    code_content="x",
                    expected="x",
                    actual="y",
                    correct=False,
                )
            )
        await session.commit()

    item = await _fetch_item(doc_id)
    assert item["mastery_pct"] == pytest.approx(0.0, abs=0.01)
