"""Unit tests for structured rubric scoring in teach-back (S156).

AC: valid rubric JSON stored correctly, malformed JSON fallback to null, missed_points count.
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import FlashcardModel, TeachbackResultModel
from app.routers.study import _parse_rubric

# ---------------------------------------------------------------------------
# Pure function tests for _parse_rubric
# ---------------------------------------------------------------------------

VALID_RUBRIC = {
    "accuracy": {"score": 82, "evidence": "The source says events are immutable records."},
    "completeness": {"score": 55, "missed_points": ["event replay", "eventual consistency"]},
    "clarity": {"score": 90, "evidence": "Explanation was well-structured."},
}


def test_parse_rubric_valid_json():
    """_parse_rubric returns a dict with all 3 keys when given valid JSON."""
    raw = json.dumps(VALID_RUBRIC)
    result = _parse_rubric(raw)
    assert result is not None
    assert set(result.keys()) == {"accuracy", "completeness", "clarity"}
    assert result["completeness"]["missed_points"] == ["event replay", "eventual consistency"]


def test_parse_rubric_malformed_json():
    """_parse_rubric returns None (no exception) when given malformed JSON."""
    result = _parse_rubric("not json at all")
    assert result is None


def test_parse_rubric_missing_keys():
    """_parse_rubric returns None when required keys are missing."""
    raw = json.dumps({"accuracy": {"score": 80, "evidence": "ok"}})
    result = _parse_rubric(raw)
    assert result is None


def test_parse_rubric_strips_markdown_fences():
    """_parse_rubric strips ```json fences before parsing."""
    inner = json.dumps(VALID_RUBRIC)
    raw = f"```json\n{inner}\n```"
    result = _parse_rubric(raw)
    assert result is not None
    assert "accuracy" in result


# ---------------------------------------------------------------------------
# Test DB fixture (same pattern as test_feynman_router.py)
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


def _make_card(doc_id: str) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=str(uuid.uuid4()),
        question="What is event sourcing?",
        answer="Event sourcing stores state changes as immutable events.",
        source_excerpt="Events are immutable records.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


class _StubLLM:
    """Deterministic LLM stub that returns responses in sequence."""

    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    async def generate(self, prompt: str, system: str = "", **kwargs: object) -> str:
        return next(self._responses)


# Legacy teachback JSON response
_LEGACY_RESPONSE = (
    '{"score": 75, "correct_points": ["immutable events"], '
    '"missing_points": ["event replay"], "misconceptions": []}'
)

# Valid rubric JSON response
_RUBRIC_RESPONSE = json.dumps(VALID_RUBRIC)

# Malformed rubric response
_MALFORMED_RUBRIC = "this is not valid json for the rubric"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teachback_stores_rubric_json(test_db):
    """AC: valid rubric JSON from mock LLM stored correctly in rubric_json column."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _make_card(doc_id)

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routers.study.get_llm_service") as mock_llm_factory:
            mock_llm_factory.return_value = _StubLLM(_LEGACY_RESPONSE, _RUBRIC_RESPONSE)

            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Events are records."},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rubric"] is not None
    assert body["rubric"]["accuracy"]["score"] == 82
    expected_missed = ["event replay", "eventual consistency"]
    assert body["rubric"]["completeness"]["missed_points"] == expected_missed
    assert body["rubric"]["clarity"]["score"] == 90

    # Verify persisted in DB
    async with factory() as session:
        result = await session.execute(
            select(TeachbackResultModel).where(TeachbackResultModel.flashcard_id == card.id)
        )
        row = result.scalar_one_or_none()
    assert row is not None
    assert row.rubric_json is not None
    assert row.rubric_json["accuracy"]["score"] == 82


@pytest.mark.asyncio
async def test_teachback_rubric_missed_points_count(test_db):
    """AC: rubric with 2 missed_points -> completeness.missed_points has length 2."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _make_card(doc_id)

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routers.study.get_llm_service") as mock_llm_factory:
            mock_llm_factory.return_value = _StubLLM(_LEGACY_RESPONSE, _RUBRIC_RESPONSE)

            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Events store changes."},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rubric"] is not None
    assert len(body["rubric"]["completeness"]["missed_points"]) == 2


@pytest.mark.asyncio
async def test_teachback_malformed_rubric_no_500(test_db):
    """AC: malformed LLM rubric JSON -> HTTP 200, response.rubric is null (no 500 error)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _make_card(doc_id)

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routers.study.get_llm_service") as mock_llm_factory:
            mock_llm_factory.return_value = _StubLLM(_LEGACY_RESPONSE, _MALFORMED_RUBRIC)

            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Events are mutable."},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rubric"] is None
    # Legacy fields still present
    assert "score" in body
    assert isinstance(body["score"], int)
