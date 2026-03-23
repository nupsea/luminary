"""Tests for FSRSService.get_struggling_cards and GET /study/struggling."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FlashcardModel, ReviewEventModel

# ---------------------------------------------------------------------------
# Fixtures
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


def _make_doc(doc_id: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Struggling Test Doc",
        format="txt",
        content_type="book",
        word_count=500,
        page_count=10,
        file_path="/tmp/struggling_test.txt",
        stage="complete",
    )


def _make_card(doc_id: str, card_id: str | None = None) -> FlashcardModel:
    return FlashcardModel(
        id=card_id or str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=None,
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
        fsrs_stability=0.0,
    )


def _make_review(
    card_id: str,
    rating: str = "again",
    days_ago: int = 0,
    session_id: str | None = None,
) -> ReviewEventModel:
    reviewed_at = datetime.now(UTC) - timedelta(days=days_ago)
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id=session_id or str(uuid.uuid4()),
        flashcard_id=card_id,
        rating=rating,
        is_correct=(rating in ("good", "easy")),
        reviewed_at=reviewed_at,
    )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


async def test_get_struggling_cards_returns_card_with_3_agains(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, card_id))
        for _ in range(3):
            session.add(_make_review(card_id, "again", days_ago=1))
        await session.commit()

    from app.services.fsrs_service import get_fsrs_service

    async with factory() as session:
        svc = get_fsrs_service()
        results = await svc.get_struggling_cards(session, document_id=doc_id)

    assert len(results) == 1
    assert results[0]["flashcard_id"] == card_id
    assert results[0]["again_count"] == 3


async def test_card_with_2_agains_not_returned(test_db):
    """2 again ratings (below threshold of 3) should not be returned."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, card_id))
        for _ in range(2):
            session.add(_make_review(card_id, "again", days_ago=1))
        await session.commit()

    from app.services.fsrs_service import get_fsrs_service

    async with factory() as session:
        svc = get_fsrs_service()
        results = await svc.get_struggling_cards(session, document_id=doc_id)

    assert len(results) == 0


async def test_old_agains_excluded_from_window(test_db):
    """Again ratings older than the window (default 14 days) are excluded."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, card_id))
        # 3 agains at 20 days ago -- outside 14-day window
        for _ in range(3):
            session.add(_make_review(card_id, "again", days_ago=20))
        await session.commit()

    from app.services.fsrs_service import get_fsrs_service

    async with factory() as session:
        svc = get_fsrs_service()
        results = await svc.get_struggling_cards(session, document_id=doc_id)

    assert len(results) == 0


async def test_good_ratings_not_counted(test_db):
    """Only 'again' ratings count towards the threshold."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, card_id))
        for _ in range(5):
            session.add(_make_review(card_id, "good", days_ago=1))
        await session.commit()

    from app.services.fsrs_service import get_fsrs_service

    async with factory() as session:
        svc = get_fsrs_service()
        results = await svc.get_struggling_cards(session, document_id=doc_id)

    assert len(results) == 0


# ---------------------------------------------------------------------------
# Endpoint test
# ---------------------------------------------------------------------------


async def test_struggling_endpoint_returns_struggling_card(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, card_id))
        for _ in range(3):
            session.add(_make_review(card_id, "again", days_ago=1))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/struggling?document_id={doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["flashcard_id"] == card_id
    assert data[0]["again_count"] == 3
    assert "question" in data[0]
    assert "source_section_id" in data[0]


async def test_struggling_endpoint_empty_when_no_struggles(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/struggling?document_id={doc_id}")

    assert resp.status_code == 200
    assert resp.json() == []
