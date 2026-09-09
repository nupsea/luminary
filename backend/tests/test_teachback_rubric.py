"""The teach-back rubric, which is read off the evaluation call rather than asked for.

It used to be a second LLM call handed the card's own answer as its source, so
the three scores the learner reads graded them against the card instead of
against the document. Folding it into the evaluation removed that second,
ungrounded judge and took one round trip off every submission.

What these guard: a rubric appears only when the evaluator actually produced all
three numbers, an absent or out-of-range dimension yields null rather than a
filled-in default, and the evidence shown is the verified quote.
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
from app.routers.study import (
    _parse_teachback_response,
    _rubric_from_evaluation,
    _score_from_dimensions,
)

# Pure function tests for _rubric_from_evaluation

EVIDENCE = "Events are immutable records."

FULL_EVALUATION = {
    "score": 75,
    "correct_points": ["immutable events"],
    "missing_points": ["event replay", "eventual consistency"],
    "misconceptions": [],
    "evidence": EVIDENCE,
    "accuracy": 82,
    "completeness": 55,
    "clarity": 90,
}


def test_rubric_projects_all_three_dimensions():
    """The three scores come out of the one evaluation, with its verified quote."""
    result = _rubric_from_evaluation(FULL_EVALUATION, EVIDENCE)
    assert result is not None
    assert set(result.keys()) == {"accuracy", "completeness", "clarity"}
    assert result["accuracy"]["score"] == 82
    assert result["accuracy"]["evidence"] == EVIDENCE
    # Clarity is a number and no remark: a free-text field asked for after the
    # integers broke the model's JSON often enough to cost the learner the score.
    assert result["clarity"]["evidence"] == ""
    assert result["completeness"]["missed_points"] == [
        "event replay",
        "eventual consistency",
    ]


def test_rubric_uses_the_verified_quote_not_the_claimed_one():
    """An unverifiable quote is dropped upstream; the rubric must show what
    survived that check, never what the model claimed to be quoting."""
    result = _rubric_from_evaluation(FULL_EVALUATION, "")
    assert result is not None
    assert result["accuracy"]["evidence"] == ""


@pytest.mark.parametrize(
    ("label", "missing"),
    [("accuracy", "accuracy"), ("completeness", "completeness"), ("clarity", "clarity")],
)
def test_rubric_is_null_when_a_dimension_is_absent(label, missing):
    """No default fills the gap: a rubric built from a number nobody produced is
    a measurement that did not happen."""
    parsed = {k: v for k, v in FULL_EVALUATION.items() if k != missing}
    assert _rubric_from_evaluation(parsed, EVIDENCE) is None, label


@pytest.mark.parametrize("value", [-1, 101, "82", 82.5, None, True])
def test_rubric_is_null_when_a_dimension_is_not_a_score(value):
    """Out of range, wrong type, or a bool masquerading as an int."""
    parsed = {**FULL_EVALUATION, "accuracy": value}
    assert _rubric_from_evaluation(parsed, EVIDENCE) is None


def test_rubric_survives_a_missing_points_field_of_the_wrong_shape():
    parsed = {**FULL_EVALUATION, "missing_points": "event replay"}
    result = _rubric_from_evaluation(parsed, EVIDENCE)
    assert result is not None
    assert result["completeness"]["missed_points"] == []


# Test DB fixture (same pattern as test_feynman_router.py)


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


# One call carries both the score and the three dimensions.
_FULL_RESPONSE = json.dumps(FULL_EVALUATION)

# A model that answered the two scoring dimensions but not clarity. Small local
# models drop a field, and clarity does not reach the score, so it must cost the
# breakdown and nothing else.
_NO_CLARITY_RESPONSE = json.dumps(
    {
        "correct_points": ["immutable events"],
        "missing_points": ["event replay"],
        "misconceptions": [],
        "accuracy": 82,
        "completeness": 55,
    }
)

# A model that answered neither. There is no score to show: the headline is
# computed from these two, so their absence is a verdict that did not happen.
_NO_DIMENSIONS_RESPONSE = json.dumps(
    {
        "score": 75,
        "correct_points": ["immutable events"],
        "missing_points": ["event replay"],
        "misconceptions": [],
    }
)


# Integration tests


@pytest.mark.asyncio
async def test_teachback_stores_rubric_json(test_db):
    """One LLM response yields the score and the stored rubric -- no second call.

    _StubLLM raises StopIteration on a second generate(), so this fails if the
    rubric ever goes back to being asked for separately.
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _make_card(doc_id)

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routers.study.get_llm_service") as mock_llm_factory:
            mock_llm_factory.return_value = _StubLLM(_FULL_RESPONSE)

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
            mock_llm_factory.return_value = _StubLLM(_FULL_RESPONSE)

            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Events store changes."},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rubric"] is not None
    assert len(body["rubric"]["completeness"]["missed_points"]) == 2


@pytest.mark.asyncio
async def test_teachback_missing_clarity_keeps_the_score(test_db):
    """Clarity absent -> HTTP 200 with a null rubric and a score all the same.

    Never a filled-in rubric: three numbers nobody produced would read to the
    learner as three measurements that were made. But clarity carries no weight,
    so its absence may not cost the verdict.
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _make_card(doc_id)

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routers.study.get_llm_service") as mock_llm_factory:
            mock_llm_factory.return_value = _StubLLM(_NO_CLARITY_RESPONSE)

            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Events are mutable."},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rubric"] is None
    assert body["score"] == 71
    assert body["missing_points"] == ["event replay"]


@pytest.mark.asyncio
async def test_teachback_without_dimensions_is_not_scored(test_db):
    """A reply carrying only the model's own `score` is refused.

    That number is what the panel used to print above a breakdown it did not
    come from. There is nothing to compute a verdict out of here, and inventing
    one from the model's opinion is the defect this replaced.
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    card = _make_card(doc_id)

    async with factory() as session:
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.routers.study.get_llm_service") as mock_llm_factory:
            # Twice: an unreadable reply buys one retry before the verdict is
            # refused, and this one is unreadable both times.
            mock_llm_factory.return_value = _StubLLM(
                _NO_DIMENSIONS_RESPONSE, _NO_DIMENSIONS_RESPONSE
            )

            resp = await client.post(
                "/study/teachback",
                json={"flashcard_id": card.id, "user_explanation": "Events are mutable."},
            )

    assert resp.status_code == 503, resp.text


_DIMS = '"accuracy": 50, "completeness": 50'


@pytest.mark.parametrize(
    ("label", "raw", "expected"),
    [
        ("clean", "{" + _DIMS + ', "correct_points": []}', 50),
        ("fenced", "```json\n{" + _DIMS + "}\n```", 50),
        ("prose preamble", "Here is my evaluation:\n{" + _DIMS + "}", 50),
        ("trailing prose", "{" + _DIMS + "}\nHope this helps!", 50),
        ("illegal escape", "{" + _DIMS + ', "evidence": "uses \\$ sign"}', 50),
    ],
)
def test_parse_teachback_recovers_real_model_output(label, raw, expected):
    """Each of these scored 0 before: the parser fenced-stripped then json.loads'd."""
    parsed = _parse_teachback_response(raw)
    assert parsed is not None, label
    assert parsed["score"] == expected


def test_parse_teachback_computes_the_score_it_was_not_asked_for():
    """The model's own `score` is discarded even when it supplies one.

    75 is what this evaluation claimed; 71 is what its dimensions say. The panel
    prints the breakdown under the headline, so the headline has to come from it.
    """
    parsed = _parse_teachback_response(json.dumps(FULL_EVALUATION))
    assert parsed is not None
    assert FULL_EVALUATION["score"] == 75
    assert parsed["score"] == 71


@pytest.mark.parametrize(
    ("label", "accuracy", "completeness", "expected"),
    [
        # The two cases that bracket the floor, stated next to it in study.py.
        ("right but a fifth of the answer", 100, 20, 59),
        ("substance with a detail missing", 70, 50, 62),
        # Accuracy leads: the same two numbers swapped are not the same verdict,
        # because saying something the passage does not support costs more than
        # stopping short of the full answer.
        ("accurate, half the ground", 80, 50, 68),
        ("full ground, half accurate", 50, 80, 62),
        ("nothing", 0, 0, 0),
        ("everything", 100, 100, 100),
    ],
)
def test_score_from_dimensions(label, accuracy, completeness, expected):
    parsed = {"accuracy": accuracy, "completeness": completeness, "clarity": 50}
    assert _score_from_dimensions(parsed) == expected, label


def test_clarity_does_not_move_the_score():
    """Clarity is the one dimension with no passage behind it. It is shown, and
    it may not decide whether a learner passed."""
    base = {"accuracy": 80, "completeness": 70}
    scores = {_score_from_dimensions(base | {"clarity": c}) for c in (0, 50, 100)}
    assert scores == {76}


@pytest.mark.parametrize(
    ("label", "parsed"),
    [
        ("accuracy absent", {"completeness": 50}),
        ("completeness absent", {"accuracy": 50}),
        ("out of range", {"accuracy": 120, "completeness": 50}),
        ("bool", {"accuracy": True, "completeness": 50}),
        ("string", {"accuracy": "80", "completeness": 50}),
    ],
)
def test_score_from_dimensions_is_none_rather_than_defaulted(label, parsed):
    """A score assembled from numbers nobody produced is a measurement that did
    not happen. None fails the parse and buys the reply a retry."""
    assert _score_from_dimensions(parsed) is None, label


@pytest.mark.parametrize(
    "raw",
    ['{"score": 40, "correct_points": ["a', '{"correct_points": []}', "The student did well."],
)
def test_parse_teachback_returns_none_when_unreadable(raw):
    """Never a fabricated 0: the learner reads it as "you got nothing right",
    it drags the session average down, and it reaches FSRS as a failed card."""
    assert _parse_teachback_response(raw) is None
