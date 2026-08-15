"""Unit and API tests for intent eval routing (S218)."""

import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.intent_metrics import (  # noqa: E402
    compute_per_route_precision_recall,
    compute_routing_accuracy,
)
from evals.lib.scoring_history import append_history  # noqa: E402


def test_routing_accuracy_with_synthetic_samples():
    samples = [
        {"expected_route": "summary", "predicted_route": "summary"},
        {"expected_route": "graph", "predicted_route": "graph"},
        {"expected_route": "comparative", "predicted_route": "search"},
        {"expected_route": "search", "predicted_route": "search"},
    ]
    assert compute_routing_accuracy(samples) == pytest.approx(0.75)


def test_per_route_precision_recall_with_synthetic_samples():
    samples = [
        {"expected_route": "summary", "predicted_route": "summary"},
        {"expected_route": "summary", "predicted_route": "search"},
        {"expected_route": "search", "predicted_route": "summary"},
        {"expected_route": "search", "predicted_route": "search"},
    ]
    metrics = compute_per_route_precision_recall(samples)
    assert metrics["summary"]["precision"] == pytest.approx(0.5)
    assert metrics["summary"]["recall"] == pytest.approx(0.5)
    assert metrics["search"]["precision"] == pytest.approx(0.5)
    assert metrics["search"]["recall"] == pytest.approx(0.5)


def test_intent_history_persists_metrics(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history(
        "intents",
        "classifier",
        {"routing_accuracy": 0.9, "per_route": {"search": {"precision": 1.0, "recall": 1.0}}},
        True,
        eval_kind="intent",
        path=target,
    )
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "intent"
    assert row["routing_accuracy"] == 0.9
    assert row["per_route"]["search"]["precision"] == 1.0


@pytest.mark.asyncio
async def test_classify_only_returns_valid_route():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/qa/classify-only", json={"question": "summarize this book"})
    assert resp.status_code == 200
    assert resp.json()["chosen_route"] in {"summary", "graph", "comparative", "search"}


@pytest.mark.asyncio
async def test_classify_only_can_run_the_fallback_the_chat_graph_runs(monkeypatch):
    """The heuristic alone is a floor. Below confidence 0.7 the chat graph asks
    the LLM, so an eval that never does measures a routing no user receives."""
    import app.routers.qa as qa_module

    async def _fake_fallback(question, default, scope="all"):
        return "comparative"

    monkeypatch.setattr(qa_module, "_llm_classify_fallback", _fake_fallback)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # A bare phrase the heuristic cannot place: catch-all, confidence 0.5.
        body = {"question": "the Vantari protocol against the Ostrek cipher"}
        without = (await client.post("/qa/classify-only", json=body)).json()
        with_llm = (
            await client.post("/qa/classify-only?llm_fallback=true", json=body)
        ).json()

    assert without["source"] == "heuristic"
    assert without["confidence"] < 0.7
    assert with_llm["source"] == "llm"
    assert with_llm["chosen_route"] == "comparative"


@pytest.mark.asyncio
async def test_a_confident_heuristic_never_reaches_the_llm(monkeypatch):
    """The risk the fallback cannot cover: a heuristic that is confidently wrong
    is never second-guessed. Shapes fire at 0.8 and so lock the LLM out."""
    import app.routers.qa as qa_module

    async def _must_not_run(question, default, scope="all"):
        raise AssertionError("fallback ran for a confident heuristic answer")

    monkeypatch.setattr(qa_module, "_llm_classify_fallback", _must_not_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/qa/classify-only?llm_fallback=true", json={"question": "Summarize this document"}
        )

    assert resp.json() == {
        **resp.json(),
        "chosen_route": "summary",
        "source": "heuristic",
    }
