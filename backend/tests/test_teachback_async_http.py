"""POST /study/teachback/async and GET /study/teachback/results over HTTP."""

import asyncio
import importlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import FlashcardModel, StudySessionModel, TeachbackResultModel

_MODULE = "app.services.teachback_service"

_EVALUATION = json.dumps(
    {
        "correct_points": ["immutable events"],
        "missing_points": [["event replay"]],
        "misconceptions": [],
        "accuracy": 82,
        "completeness": 55,
        "clarity": 90,
        "evidence": "not in any passage",
    }
)


class _StubLLM:
    async def generate(self, prompt: str, system: str = "", **kwargs: object) -> str:
        return _EVALUATION


def _card() -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        question="What is event sourcing?",
        answer="Storing state as a log of events.",
        source_excerpt="Storing state as a log of events.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
    )


async def _client_call(method: str, url: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_async_submit_is_pending_then_graded(test_db):
    _, factory, _ = test_db
    card = _card()
    sess = StudySessionModel(
        id=str(uuid.uuid4()),
        started_at=datetime.now(UTC),
        cards_reviewed=0,
        cards_correct=0,
        mode="flashcard",
    )
    async with factory() as session:
        session.add_all([card, sess])
        await session.commit()

    module = importlib.import_module(_MODULE)
    with patch(f"{_MODULE}.get_llm_service", return_value=_StubLLM()):
        resp = await _client_call(
            "POST",
            "/study/teachback/async",
            json={
                "flashcard_id": card.id,
                "user_explanation": "Events are stored, not state.",
                "session_id": sess.id,
            },
        )
        assert resp.status_code == 200, resp.text
        tb_id = resp.json()["id"]
        await asyncio.gather(*list(module._background_tasks))

    body = (await _client_call("GET", "/study/teachback/results", params={"ids": tb_id})).json()
    [item] = body["results"]
    assert item["status"] == "complete"
    assert item["question"] == card.question
    assert item["expected_answer"] == card.answer
    assert item["score"] == module._score_from_dimensions(json.loads(_EVALUATION))
    assert item["correct_points"] == ["immutable events"]
    assert item["missing_points"] == ["event replay"]
    assert item["user_explanation"] == "Events are stored, not state."
    # The quote is not in the passage, so accuracy carries no evidence.
    assert item["rubric"]["accuracy"]["score"] == 82

    async with factory() as session:
        assert (await session.get(StudySessionModel, sess.id)).mode == "teachback"


@pytest.mark.asyncio
async def test_results_hide_the_verdict_until_complete(test_db):
    _, factory, _ = test_db
    card = _card()
    pending = TeachbackResultModel(
        id=str(uuid.uuid4()),
        flashcard_id=card.id,
        user_explanation="draft",
        score=0,
        correct_points=["x"],
        status="pending",
    )
    orphan = TeachbackResultModel(
        id=str(uuid.uuid4()),
        flashcard_id="deleted-card",
        user_explanation="e",
        score=70,
        status="complete",
    )
    async with factory() as session:
        session.add_all([card, pending, orphan])
        await session.commit()

    ids = f"{pending.id}, {orphan.id},missing"
    body = (await _client_call("GET", "/study/teachback/results", params={"ids": ids})).json()
    by_id = {r["id"]: r for r in body["results"]}
    assert set(by_id) == {pending.id, orphan.id}
    assert by_id[pending.id]["score"] is None
    assert by_id[pending.id]["correct_points"] == []
    assert by_id[pending.id]["user_explanation"] is None
    assert by_id[pending.id]["rubric"] is None
    assert (by_id[orphan.id]["question"], by_id[orphan.id]["score"]) == ("", 70)


@pytest.mark.asyncio
async def test_results_with_no_ids(test_db):
    body = (await _client_call("GET", "/study/teachback/results", params={"ids": " , "})).json()
    assert body == {"results": []}


@pytest.mark.asyncio
async def test_async_submit_for_a_missing_card(test_db):
    resp = await _client_call(
        "POST",
        "/study/teachback/async",
        json={"flashcard_id": "nope", "user_explanation": "x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Flashcard not found"
