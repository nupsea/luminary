"""Tests for FSRSService.get_struggling_cards and GET /study/struggling."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.main import app
from app.models import DocumentModel, FlashcardModel, ReviewEventModel
from tests.factories import make_card, make_document

# Fixtures


def _make_doc(doc_id: str | None = None) -> DocumentModel:
    return make_document(
        id=doc_id,
        title="Struggling Test Doc",
        word_count=500,
        page_count=10,
        file_path="/tmp/struggling_test.txt",
    )


def _make_card(doc_id: str, card_id: str | None = None) -> FlashcardModel:
    return make_card(
        id=card_id,
        document_id=doc_id,
        chunk_id=None,
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
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


# Service tests


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


@pytest.mark.parametrize(
    "count, rating, days_ago",
    [
        pytest.param(2, "again", 1, id="card_with_2_agains_not_returned"),
        pytest.param(3, "again", 20, id="old_agains_excluded_from_window"),
        pytest.param(5, "good", 1, id="good_ratings_not_counted"),
    ],
)
async def test_ratings_below_threshold_are_not_returned(count, rating, days_ago, test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, card_id))
        for _ in range(count):
            session.add(_make_review(card_id, rating, days_ago=days_ago))
        await session.commit()

    from app.services.fsrs_service import get_fsrs_service

    async with factory() as session:
        svc = get_fsrs_service()
        results = await svc.get_struggling_cards(session, document_id=doc_id)

    assert len(results) == 0


# Endpoint test


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
