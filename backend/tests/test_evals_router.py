"""Tests for the /evals router.

Tests:
  - test_get_results_empty_when_no_file
  - test_get_results_returns_latest_per_dataset
  - test_post_run_returns_202
  - test_post_run_invalid_dataset
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.routers.evals as evals_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app

# ---------------------------------------------------------------------------
# Shared fixture — in-memory SQLite DB
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

    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_results_empty_when_no_file(test_db, tmp_path, monkeypatch):
    """GET /evals/results returns HTTP 200 and [] when scores_history.jsonl does not exist."""
    # Point _SCORES_HISTORY_PATH to a nonexistent file
    nonexistent = tmp_path / "nonexistent_scores_history.jsonl"
    monkeypatch.setattr(evals_module, "_SCORES_HISTORY_PATH", nonexistent)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/evals/results")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_results_returns_latest_per_dataset(test_db, tmp_path, monkeypatch):
    """GET /evals/results returns latest result per dataset (2 datasets = 2 items)."""
    history_path = tmp_path / "scores_history.jsonl"

    # Two book entries with different timestamps; one paper entry
    entries = [
        {
            "timestamp": "2024-01-01T10:00:00+00:00",
            "dataset": "book",
            "model": "no-llm",
            "hr5": 0.50,
            "mrr": 0.40,
            "faithfulness": None,
            "passed": False,
        },
        {
            "timestamp": "2024-01-02T10:00:00+00:00",
            "dataset": "book",
            "model": "no-llm",
            "hr5": 0.70,
            "mrr": 0.55,
            "faithfulness": None,
            "passed": True,
        },
        {
            "timestamp": "2024-01-01T12:00:00+00:00",
            "dataset": "paper",
            "model": "no-llm",
            "hr5": 0.60,
            "mrr": 0.48,
            "faithfulness": None,
            "passed": True,
        },
    ]
    with history_path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    monkeypatch.setattr(evals_module, "_SCORES_HISTORY_PATH", history_path)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/evals/results")

    assert resp.status_code == 200
    data = resp.json()

    # Should return exactly 2 items (one per dataset)
    assert len(data) == 2

    datasets = {item["dataset"] for item in data}
    assert datasets == {"book", "paper"}

    # Latest book entry should be the one from 2024-01-02 with hr5=0.70
    book_item = next(item for item in data if item["dataset"] == "book")
    assert book_item["hit_rate_5"] == pytest.approx(0.70)
    assert book_item["mrr"] == pytest.approx(0.55)
    assert book_item["passed_thresholds"] is True


@pytest.mark.asyncio
async def test_post_run_returns_202(test_db, monkeypatch):
    """POST /evals/run {dataset: 'book'} returns HTTP 202 with status='started'."""
    # Ensure golden file exists so the 404 check passes
    golden_dir = test_db / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    (golden_dir / "book.jsonl").write_text('{"question": "test"}')

    # Patch the background subprocess so tests don't actually run evals.
    # Close the coroutine explicitly to suppress 'coroutine was never awaited' warnings.
    monkeypatch.setattr(evals_module, "_fire_and_forget", lambda coro: coro.close())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/evals/run", json={"dataset": "book"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "started"
    assert body["dataset"] == "book"


@pytest.mark.asyncio
async def test_post_run_invalid_dataset(test_db):
    """POST /evals/run with invalid dataset returns HTTP 404."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/evals/run", json={"dataset": "invalid"})

    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset", ["book_time_machine", "book_alice", "book_odyssey"])
async def test_post_run_per_book_dataset(test_db, monkeypatch, dataset):
    """POST /evals/run with per-book dataset names returns HTTP 202 when the JSONL file exists."""
    golden_dir = test_db / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    (golden_dir / f"{dataset}.jsonl").write_text('{"question": "test"}')

    monkeypatch.setattr(evals_module, "_fire_and_forget", lambda coro: coro.close())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/evals/run", json={"dataset": dataset})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "started"
    assert body["dataset"] == dataset
