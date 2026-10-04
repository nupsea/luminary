"""GET /study/decay-debt, /study/calibration-stats and per-section stability in /study/stats."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    ReviewEventModel,
    SectionModel,
)

_NOW = datetime.now(UTC)


def _doc(doc_id: str) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=f"Title {doc_id}",
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path="/tmp/x.txt",
        stage="complete",
    )


def _card(document_id, stability, due_in_days, chunk_id=None) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        chunk_id=chunk_id,
        question="Q?",
        answer="A.",
        source_excerpt="A.",
        fsrs_state="review",
        fsrs_stability=stability,
        fsrs_difficulty=0.5,
        due_date=None if due_in_days is None else _NOW + timedelta(days=due_in_days),
    )


async def _get(path: str, **params):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_decay_debt_groups_at_risk_cards_weakest_first(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add_all(
            [
                _doc("weak"),
                _doc("slipping"),
                _card("weak", 10.0, -30),  # retention e^-3, long past the threshold
                _card("weak", 100.0, 5),  # 22 days of margin: not at risk
                _card("slipping", 20.0, -1),  # retention 0.951, crosses 0.80 in ~3 days
                _card("ghost", 5.0, -10),  # document row gone
                _card(None, 5.0, -10),  # note card: not a document's debt
                _card("weak", 0.0, -10),  # never reviewed
                _card("weak", 5.0, None),  # unscheduled
            ]
        )
        await session.commit()

    body = await _get("/study/decay-debt")
    assert body["total_at_risk"] == 3
    assert [
        (i["document_id"], i["document_title"], i["card_count"], i["avg_retention"])
        for i in body["items"]
    ] == [
        ("weak", "Title weak", 1, 0.05),
        ("ghost", "(unknown)", 1, 0.135),
        ("slipping", "Title slipping", 1, 0.951),
    ]
    assert [i["due_within_days"] for i in body["items"]] == [0, 0, 3]

    limited = await _get("/study/decay-debt", limit=1)
    assert [i["document_id"] for i in limited["items"]] == ["weak"]
    assert limited["total_at_risk"] == 3


@pytest.mark.asyncio
async def test_decay_debt_empty(test_db):
    assert await _get("/study/decay-debt") == {"items": [], "total_at_risk": 0}


def _event(predicted, actual, at: datetime) -> ReviewEventModel:
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id="s",
        flashcard_id="c",
        rating=actual,
        is_correct=True,
        reviewed_at=at,
        predicted_rating=predicted,
    )


@pytest.mark.asyncio
async def test_calibration_stats_by_week(test_db):
    _, factory, _ = test_db
    last_monday = (_NOW - timedelta(days=_NOW.weekday() + 7)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    this_monday = last_monday + timedelta(days=7, hours=-12)
    async with factory() as session:
        session.add_all(
            [
                _event("good", "good", last_monday),
                _event("hard", "good", last_monday + timedelta(days=1)),
                _event("easy", "easy", this_monday),
                _event(None, "good", last_monday),  # no prediction made
                _event("good", "good", _NOW - timedelta(days=40)),  # outside the window
            ]
        )
        await session.commit()

    body = await _get("/study/calibration-stats", days=30)
    assert body["total_predictions"] == 3
    assert body["overall_match_rate"] == 0.667
    assert body["weeks"] == [
        {
            "week_start": last_monday.date().isoformat(),
            "total": 2,
            "matched": 1,
            "match_rate": 0.5,
        },
        {"week_start": this_monday.date().isoformat(), "total": 1, "matched": 1, "match_rate": 1.0},
    ]


@pytest.mark.asyncio
async def test_calibration_stats_empty(test_db):
    body = await _get("/study/calibration-stats")
    assert body == {"overall_match_rate": None, "total_predictions": 0, "weeks": []}


@pytest.mark.asyncio
async def test_stats_per_section_stability_weakest_first(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add_all(
            [
                _doc("d"),
                SectionModel(id="s1", document_id="d", heading="One", level=1, section_order=0),
                SectionModel(id="s2", document_id="d", heading="Two", level=1, section_order=1),
                ChunkModel(id="k1", document_id="d", section_id="s1", text="t", chunk_index=0),
                ChunkModel(id="k2", document_id="d", section_id="s2", text="t", chunk_index=1),
                _card("d", 10.0, 3, chunk_id="k1"),
                _card("d", 20.0, 3, chunk_id="k1"),
                _card("d", 2.0, 3, chunk_id="k2"),
                _card("d", 50.0, 3, chunk_id="missing"),
            ]
        )
        await session.commit()

    body = await _get("/study/stats/d")
    assert body["per_section_stability"] == [
        {"section_heading": "Two", "avg_stability": 2.0, "card_count": 1},
        {"section_heading": "One", "avg_stability": 15.0, "card_count": 2},
        {"section_heading": None, "avg_stability": 50.0, "card_count": 1},
    ]
