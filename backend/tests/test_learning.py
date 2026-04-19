"""Tests for the learning engine — gap detection, teach-back, and misconception tracking."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel, MisconceptionModel, TeachbackResultModel
from app.routers.study import _parse_teachback_response

# ---------------------------------------------------------------------------
# Test DB fixture
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


def _make_card(
    doc_id: str | None = None,
    card_id: str | None = None,
    fsrs_stability: float = 0.5,
    reps: int = 2,
    fsrs_state: str = "learning",
    **kwargs,
) -> FlashcardModel:
    now = datetime.now(UTC)
    defaults = {
        "id": card_id or str(uuid.uuid4()),
        "document_id": doc_id or str(uuid.uuid4()),
        "chunk_id": str(uuid.uuid4()),
        "question": "What is spaced repetition?",
        "answer": "A learning method using increasing intervals.",
        "source_excerpt": "Spaced repetition...",
        "fsrs_state": fsrs_state,
        "fsrs_stability": fsrs_stability,
        "fsrs_difficulty": 3.0,
        "due_date": now,
        "reps": reps,
        "lapses": 0,
        "created_at": now,
    }
    defaults.update(kwargs)
    return FlashcardModel(**defaults)


# ---------------------------------------------------------------------------
# _parse_teachback_response unit tests
# ---------------------------------------------------------------------------


def test_parse_teachback_response_valid_json():
    """_parse_teachback_response parses a well-formed JSON string."""
    raw = json.dumps(
        {
            "score": 75,
            "correct_points": ["Correct point A"],
            "missing_points": ["Missing B"],
            "misconceptions": [],
        }
    )
    result = _parse_teachback_response(raw)
    assert result["score"] == 75
    assert result["correct_points"] == ["Correct point A"]


def test_parse_teachback_response_strips_markdown_fences():
    """_parse_teachback_response strips ```json ... ``` fences."""
    raw = (
        "```json\n"
        '{"score": 80, "correct_points": [], "missing_points": [], "misconceptions": []}\n'
        "```"
    )
    result = _parse_teachback_response(raw)
    assert result["score"] == 80


def test_parse_teachback_response_returns_empty_on_bad_json():
    """_parse_teachback_response returns zero-score empty dict on unparseable input."""
    result = _parse_teachback_response("not valid JSON at all")
    assert result.get("score", 0) == 0
    assert result.get("correct_points", []) == []


# ---------------------------------------------------------------------------
# GET /study/gaps/{document_id} tests
# ---------------------------------------------------------------------------


async def test_get_gaps_returns_weak_cards_grouped(test_db):
    """GET /study/gaps returns sections with fragile cards (stability < 2, reps > 1)."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    # Weak card: low stability, multiple reps
    weak_card = _make_card(doc_id=doc_id, fsrs_stability=0.8, reps=3)
    # Strong card: high stability — should not appear
    strong_card = _make_card(doc_id=doc_id, fsrs_stability=5.0, reps=3)
    # Card with reps=0 — not seen, should not appear
    new_card = _make_card(doc_id=doc_id, fsrs_stability=0.3, reps=0)

    async with factory() as session:
        session.add(weak_card)
        session.add(strong_card)
        session.add(new_card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/gaps/{doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["weak_card_count"] == 1
    assert data[0]["avg_stability"] == pytest.approx(0.8, abs=0.01)
    assert weak_card.question in data[0]["sample_questions"]


async def test_get_gaps_empty_when_no_weak_cards(test_db):
    """GET /study/gaps returns empty list when no weak cards exist."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    strong = _make_card(doc_id=doc_id, fsrs_stability=8.0, reps=5)

    async with factory() as session:
        session.add(strong)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/gaps/{doc_id}")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_gaps_sorted_by_avg_stability_asc(test_db):
    """GET /study/gaps returns results sorted by avg_stability ascending."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    card_low = _make_card(doc_id=doc_id, fsrs_stability=0.2, reps=2, question="Low Q")
    card_mid = _make_card(doc_id=doc_id, fsrs_stability=1.5, reps=2, question="Mid Q")

    async with factory() as session:
        session.add(card_low)
        session.add(card_mid)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/gaps/{doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    stabilities = [d["avg_stability"] for d in data]
    # Should be sorted ascending (most fragile first)
    assert stabilities == sorted(stabilities)


# ---------------------------------------------------------------------------
# POST /study/teachback tests
# ---------------------------------------------------------------------------


async def test_teachback_returns_score_and_feedback(test_db):
    """POST /study/teachback calls LLM and returns parsed score/feedback."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    llm_response = json.dumps(
        {
            "score": 75,
            "correct_points": ["Correctly identified intervals"],
            "missing_points": ["Did not mention forgetting curve"],
            "misconceptions": [],
        }
    )

    with patch("app.routers.study.get_llm_service") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=llm_response)
        mock_get_llm.return_value = mock_llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "It's about spacing reviews."},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 75
    assert "Correctly identified intervals" in data["correct_points"]
    assert data["correction_flashcard_id"] is None  # score >= 60


async def test_teachback_score_below_60_creates_misconception_rows(test_db):
    """POST /study/teachback with score < 60 creates MisconceptionModel rows."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    llm_eval_response = json.dumps(
        {
            "score": 40,
            "correct_points": [],
            "missing_points": ["Everything"],
            "misconceptions": ["Confuses spaced repetition with massed practice"],
        }
    )
    correction_response = json.dumps(
        {
            "question": "What distinguishes spaced repetition from massed practice?",
            "answer": "Spaced repetition uses increasing intervals; massed practice is cramming.",
            "source_excerpt": "Spaced repetition...",
        }
    )

    # S156: rubric call is now the 2nd LLM call; correction flashcard is the 3rd
    rubric_response = "{}"  # invalid rubric JSON -> graceful fallback to null rubric

    with patch("app.routers.study.get_llm_service") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[llm_eval_response, rubric_response, correction_response]
        )
        mock_get_llm.return_value = mock_llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/study/teachback",
                json={
                    "flashcard_id": card.id,
                    "user_explanation": "It's the same as cramming but slower.",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 40
    assert data["correction_flashcard_id"] is not None

    # Verify MisconceptionModel row was created
    from sqlalchemy import select

    async with factory() as session:
        result = await session.execute(
            select(MisconceptionModel).where(MisconceptionModel.flashcard_id == card.id)
        )
        rows = result.scalars().all()
    assert len(rows) == 1
    assert "massed practice" in rows[0].correction_note


async def test_teachback_score_below_60_creates_correction_flashcard(test_db):
    """POST /study/teachback with score < 60 creates a correction flashcard in SQLite."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    llm_eval_response = json.dumps(
        {
            "score": 35,
            "correct_points": [],
            "missing_points": [],
            "misconceptions": ["Wrong definition"],
        }
    )
    correction_response = json.dumps(
        {
            "question": "Correction Q",
            "answer": "Correction A",
            "source_excerpt": "...",
        }
    )

    # S156: rubric call is now the 2nd LLM call; correction flashcard is the 3rd
    rubric_response = "{}"  # invalid rubric JSON -> graceful fallback to null rubric

    with patch("app.routers.study.get_llm_service") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[llm_eval_response, rubric_response, correction_response]
        )
        mock_get_llm.return_value = mock_llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "wrong"},
            )

    correction_id = resp.json()["correction_flashcard_id"]
    assert correction_id is not None

    # Verify correction flashcard exists
    from sqlalchemy import select

    async with factory() as session:
        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.id == correction_id)
        )
        correction_card = result.scalar_one_or_none()
    assert correction_card is not None
    assert correction_card.question == "Correction Q"


async def test_teachback_stores_teachback_result(test_db):
    """POST /study/teachback always persists a TeachbackResultModel row."""
    _, factory, _ = test_db
    card = _make_card()

    async with factory() as session:
        session.add(card)
        await session.commit()

    llm_response = json.dumps(
        {
            "score": 90,
            "correct_points": ["Good"],
            "missing_points": [],
            "misconceptions": [],
        }
    )

    with patch("app.routers.study.get_llm_service") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=llm_response)
        mock_get_llm.return_value = mock_llm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Correct explanation."},
            )

    from sqlalchemy import select

    async with factory() as session:
        result = await session.execute(
            select(TeachbackResultModel).where(TeachbackResultModel.flashcard_id == card.id)
        )
        row = result.scalar_one_or_none()
    assert row is not None
    assert row.score == 90


async def test_teachback_404_for_missing_flashcard(test_db):
    """POST /study/teachback returns 404 for a non-existent flashcard."""
    _, _factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/study/teachback",
            json={"flashcard_id": "nonexistent", "user_explanation": "something"},
        )

    assert resp.status_code == 404
