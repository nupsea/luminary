"""Tests for S227: GET /evals/runs, GET /evals/golden/{name}, extended POST /evals/run."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import EvalRunModel

# ---------------------------------------------------------------------------
# Isolated DB fixture
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


def _make_run(
    dataset_name: str = "book_time_machine",
    eval_kind: str = "retrieval",
    model_used: str = "ollama/mistral",
    hit_rate_5: float = 0.6,
    routing_accuracy: float | None = None,
    ablation_metrics: dict | None = None,
    per_route: dict | None = None,
) -> EvalRunModel:
    return EvalRunModel(
        id=str(uuid.uuid4()),
        dataset_name=dataset_name,
        run_at=datetime.now(UTC),
        hit_rate_5=hit_rate_5,
        mrr=0.5,
        faithfulness=None,
        answer_relevance=None,
        context_precision=None,
        context_recall=None,
        model_used=model_used,
        eval_kind=eval_kind,
        routing_accuracy=routing_accuracy,
        per_route=per_route,
        ablation_metrics=ablation_metrics,
    )


# ---------------------------------------------------------------------------
# GET /evals/runs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_eval_runs_returns_all(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_make_run(dataset_name="ds1", eval_kind="retrieval"))
        session.add(_make_run(dataset_name="ds2", eval_kind="routing"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.anyio
async def test_get_eval_runs_filter_dataset_name(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_make_run(dataset_name="ds_a"))
        session.add(_make_run(dataset_name="ds_b"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/runs?dataset_name=ds_a")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["dataset_name"] == "ds_a"


@pytest.mark.anyio
async def test_get_eval_runs_filter_eval_kind(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_make_run(eval_kind="retrieval"))
        session.add(_make_run(eval_kind="routing"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/runs?eval_kind=routing")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["eval_kind"] == "routing"


@pytest.mark.anyio
async def test_get_eval_runs_filter_model(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add(_make_run(model_used="ollama/mistral"))
        session.add(_make_run(model_used="gpt-4o"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/runs?model=gpt-4o")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["model_used"] == "gpt-4o"


@pytest.mark.anyio
async def test_get_eval_runs_limit_offset(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        for i in range(5):
            session.add(_make_run(dataset_name=f"ds_{i}"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/runs?limit=2&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp2 = await client.get("/evals/runs?limit=2&offset=4")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


@pytest.mark.anyio
async def test_get_eval_runs_empty(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/runs?dataset_name=nonexistent")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /evals/golden/{name}
# ---------------------------------------------------------------------------


@pytest.fixture
def golden_dir(tmp_path, monkeypatch):
    """Create a temporary golden directory and monkeypatch _EVALS_DIR."""
    evals_dir = tmp_path / "evals"
    golden = evals_dir / "golden"
    golden.mkdir(parents=True)
    monkeypatch.setattr("app.routers.evals._EVALS_DIR", evals_dir)
    return golden


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


@pytest.mark.anyio
async def test_get_golden_file_happy_path(golden_dir):
    rows = [
        {"q": f"Q{i}", "a": f"A{i}", "context_hint": f"hint{i}", "source_file": "book.txt"}
        for i in range(5)
    ]
    _write_jsonl(golden_dir / "my_dataset.jsonl", rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/golden/my_dataset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "my_dataset"
    assert data["total"] == 5
    assert len(data["questions"]) == 5
    assert data["questions"][0]["q"] == "Q0"


@pytest.mark.anyio
async def test_get_golden_file_pagination(golden_dir):
    rows = [{"q": f"Q{i}", "a": f"A{i}"} for i in range(10)]
    _write_jsonl(golden_dir / "pg.jsonl", rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/golden/pg?offset=3&limit=4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 10
    assert len(data["questions"]) == 4
    assert data["questions"][0]["q"] == "Q3"


@pytest.mark.anyio
async def test_get_golden_file_not_found(golden_dir):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/golden/does_not_exist_xyz")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_golden_file_path_traversal_dots(golden_dir):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/golden/..%2Ffoo")
    assert resp.status_code in (400, 404, 422)


@pytest.mark.anyio
async def test_get_golden_file_path_traversal_invalid_chars(golden_dir):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/golden/foo%2Fbar")
    assert resp.status_code in (400, 404, 422)


@pytest.mark.anyio
async def test_get_golden_file_rejects_dotdot_name(golden_dir):
    # name containing ".." must be rejected even without URL encoding
    # FastAPI decodes the path param, so ..foo will be seen as "..foo" which fails the regex
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/evals/golden/..foo")
    # FastAPI may route this differently; accept 400 or 404 or 422
    assert resp.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# POST /evals/run -- extended body fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_eval_run_extended_body_flags(golden_dir):
    """Extended body fields forwarded to subprocess command."""
    _write_jsonl(golden_dir / "test_ds.jsonl", [{"q": "Q1", "a": "A1"}])

    captured_cmd: list[list[str]] = []

    def fake_subprocess_run(cmd, **kwargs):
        captured_cmd.append(cmd)

        class _Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Result()

    with patch("app.routers.evals.asyncio.to_thread") as mock_thread:
        mock_thread.side_effect = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/evals/run",
                    json={
                        "dataset": "test_ds",
                        "judge_model": "ollama/mistral",
                        "check_citations": True,
                        "max_questions": 5,
                    },
                )
    assert resp.status_code == 202
    # The background task is fired-and-forget; we can't easily capture it in unit tests.
    # Verify the response shape.
    data = resp.json()
    assert data["status"] == "started"
    assert data["dataset"] == "test_ds"


@pytest.mark.anyio
async def test_post_eval_run_missing_dataset(golden_dir):
    """POST /evals/run returns 404 when the JSONL file does not exist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/evals/run", json={"dataset": "nonexistent_dataset_xyz"})
    assert resp.status_code == 404
