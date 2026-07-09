"""Tests for GET /monitoring/traces, GET /monitoring/overview, and eval endpoints."""

import unittest.mock
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, EvalRunModel, QAHistoryModel
from app.services.eval_regression_service import detect_regressions

# Test DB fixture


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


# Helpers


def _make_document(doc_id: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Test Document",
        format="pdf",
        content_type="book",
        stage="complete",
        file_path="/tmp/test.pdf",
    )


def _make_chunk(doc_id: str) -> ChunkModel:
    return ChunkModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        text="Some text",
        chunk_index=0,
    )


def _make_qa(doc_id: str, created_at: datetime) -> QAHistoryModel:
    return QAHistoryModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        scope="single",
        question="What is X?",
        answer="X is Y.",
        citations=[],
        confidence="high",
        model_used="ollama/llama3",
        created_at=created_at,
    )


# GET /monitoring/traces


async def test_traces_phoenix_disabled(test_db, monkeypatch):
    """When PHOENIX_ENABLED=False, returns empty traces list (not a 500)."""
    monkeypatch.setenv("PHOENIX_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/traces")

    assert resp.status_code == 200
    data = resp.json()
    assert data["traces"] == []
    assert "disabled" in (data.get("message") or "").lower()

    get_settings.cache_clear()


async def test_traces_phoenix_not_running(test_db, monkeypatch):
    """When Phoenix enabled but not reachable, returns empty traces (not a 500)."""
    monkeypatch.setenv("PHOENIX_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    # Force health check to return False
    monkeypatch.setattr(
        "app.routers.monitoring._check_phoenix_running",
        lambda: __import__("asyncio").coroutine(lambda: False)(),
    )

    # Use a simpler monkeypatch approach via the module attribute
    import app.routers.monitoring as mon_module

    async def _not_running() -> bool:
        return False

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _not_running)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/traces")

    assert resp.status_code == 200
    data = resp.json()
    assert data["traces"] == []
    assert data.get("message") is not None

    get_settings.cache_clear()


async def test_traces_phoenix_running_returns_spans(test_db, monkeypatch):
    """When Phoenix running and spans available, returns them in response."""
    monkeypatch.setenv("PHOENIX_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.routers.monitoring as mon_module
    from app.routers.monitoring import TraceItem

    fake_span = TraceItem(
        span_id="abc123",
        trace_id="trace456",
        operation_name="llm.generate",
        start_time="2026-02-25T00:00:00+00:00",
        duration_ms=42.5,
        status="ok",
        attributes={"llm.model": "ollama/llama3"},
    )

    async def _running() -> bool:
        return True

    async def _fetch_spans(limit: int = 50) -> list[TraceItem]:
        return [fake_span]

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _running)
    monkeypatch.setattr(mon_module, "_fetch_phoenix_spans", _fetch_spans)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/traces")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["traces"]) == 1
    assert data["traces"][0]["span_id"] == "abc123"
    assert data["traces"][0]["operation_name"] == "llm.generate"
    assert data["traces"][0]["duration_ms"] == pytest.approx(42.5)

    get_settings.cache_clear()


# GET /monitoring/overview


async def test_overview_document_and_chunk_counts(test_db, monkeypatch):
    """GET /monitoring/overview returns correct total_documents and total_chunks."""
    _, factory, _ = test_db

    import app.routers.monitoring as mon_module

    async def _not_running() -> bool:
        return False

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _not_running)

    doc = _make_document()
    chunk1 = _make_chunk(doc.id)
    chunk2 = _make_chunk(doc.id)
    async with factory() as session:
        session.add_all([doc, chunk1, chunk2])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/overview")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_documents"] == 1
    assert data["total_chunks"] == 2


async def test_overview_qa_calls_today(test_db, monkeypatch):
    """GET /monitoring/overview counts QA calls created today (UTC)."""
    _, factory, _ = test_db

    import app.routers.monitoring as mon_module

    async def _not_running() -> bool:
        return False

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _not_running)

    doc = _make_document()
    today = datetime.now(tz=UTC).replace(tzinfo=None)  # stored as naive UTC
    yesterday = today.replace(day=today.day - 1) if today.day > 1 else today

    qa_today = _make_qa(doc.id, today)
    qa_old = _make_qa(doc.id, yesterday)
    async with factory() as session:
        session.add_all([doc, qa_today, qa_old])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/overview")

    assert resp.status_code == 200
    data = resp.json()
    assert data["qa_calls_today"] >= 1


async def test_overview_langfuse_configured_when_key_set(test_db, monkeypatch):
    """langfuse_configured=True when LANGFUSE_PUBLIC_KEY env var is non-empty."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-123")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.routers.monitoring as mon_module

    async def _not_running() -> bool:
        return False

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _not_running)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/overview")

    assert resp.status_code == 200
    assert resp.json()["langfuse_configured"] is True

    get_settings.cache_clear()


async def test_overview_phoenix_running_reflects_health_check(test_db, monkeypatch):
    """phoenix_running in overview reflects _check_phoenix_running result."""
    import app.routers.monitoring as mon_module

    async def _running() -> bool:
        return True

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _running)
    monkeypatch.setenv("PHOENIX_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/overview")

    assert resp.status_code == 200
    assert resp.json()["phoenix_running"] is True

    get_settings.cache_clear()


async def test_overview_empty_db_returns_zeros(test_db, monkeypatch):
    """GET /monitoring/overview returns 0 for all counts on empty DB."""
    import app.routers.monitoring as mon_module

    async def _not_running() -> bool:
        return False

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _not_running)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/overview")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_documents"] == 0
    assert data["total_chunks"] == 0
    assert data["qa_calls_today"] == 0


# POST /monitoring/evals/store


async def test_store_eval_run_creates_row(test_db):
    """POST /monitoring/evals/store inserts an EvalRunModel row."""
    _, factory, _ = test_db

    payload = {
        "dataset_name": "book",
        "model_used": "ollama/mistral",
        "hit_rate_5": 0.7,
        "mrr": 0.6,
        "faithfulness": 0.85,
        "answer_relevance": 0.9,
        "context_precision": 0.8,
        "context_recall": 0.75,
        "theme_coverage": 0.88,
        "no_hallucination": 0.95,
        "conciseness_pct": 1.1,
        "factuality": 0.92,
        "atomicity": 0.84,
        "clarity_avg": 4.1,
        "routing_accuracy": 0.93,
        "per_route": {"search": {"precision": 1.0, "recall": 0.9}},
        "ablation_metrics": {"vector": {"hit_rate_5": 0.5, "mrr": 0.4}},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/monitoring/evals/store", json=payload)

    assert resp.status_code == 201
    data = resp.json()
    assert data["dataset_name"] == "book"
    assert data["model_used"] == "ollama/mistral"
    assert data["hit_rate_5"] == pytest.approx(0.7)
    assert data["mrr"] == pytest.approx(0.6)
    assert data["theme_coverage"] == pytest.approx(0.88)
    assert data["no_hallucination"] == pytest.approx(0.95)
    assert data["conciseness_pct"] == pytest.approx(1.1)
    assert data["factuality"] == pytest.approx(0.92)
    assert data["atomicity"] == pytest.approx(0.84)
    assert data["clarity_avg"] == pytest.approx(4.1)
    assert data["routing_accuracy"] == pytest.approx(0.93)
    assert data["per_route"]["search"]["recall"] == pytest.approx(0.9)
    assert data["ablation_metrics"]["vector"]["mrr"] == pytest.approx(0.4)
    assert "id" in data
    assert "run_at" in data

    # Verify it's persisted in DB
    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(EvalRunModel).where(EvalRunModel.id == data["id"]))
        row = result.scalar_one_or_none()
    assert row is not None
    assert row.dataset_name == "book"


async def test_store_eval_run_with_null_ragas_scores(test_db):
    """POST /monitoring/evals/store accepts None for RAGAS metrics (LLM unavailable)."""
    payload = {
        "dataset_name": "paper",
        "model_used": "ollama/mistral",
        "hit_rate_5": 0.5,
        "mrr": 0.4,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/monitoring/evals/store", json=payload)

    assert resp.status_code == 201
    data = resp.json()
    assert data["faithfulness"] is None
    assert data["answer_relevance"] is None


# GET /monitoring/evals


async def test_get_evals_returns_run_history(test_db):
    """GET /monitoring/evals returns stored eval runs."""
    _, factory, _ = test_db

    run = EvalRunModel(
        id=str(uuid.uuid4()),
        dataset_name="notes",
        model_used="ollama/mistral",
        run_at=datetime.now(tz=UTC),
        hit_rate_5=0.8,
        mrr=0.7,
        faithfulness=None,
        answer_relevance=None,
        context_precision=None,
        context_recall=None,
    )
    async with factory() as session:
        session.add(run)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/evals")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    matching = [r for r in data if r["dataset_name"] == "notes"]
    assert len(matching) == 1
    assert matching[0]["hit_rate_5"] == pytest.approx(0.8)


async def test_get_evals_empty_when_no_runs(test_db):
    """GET /monitoring/evals returns empty list when no eval runs stored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/evals")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_evals_caps_at_10_per_dataset(test_db):
    """GET /monitoring/evals returns at most 10 rows per dataset."""
    _, factory, _ = test_db

    runs = [
        EvalRunModel(
            id=str(uuid.uuid4()),
            dataset_name="code",
            model_used="ollama/mistral",
            run_at=datetime.now(tz=UTC),
            hit_rate_5=float(i) / 15,
            mrr=None,
            faithfulness=None,
            answer_relevance=None,
            context_precision=None,
            context_recall=None,
        )
        for i in range(15)
    ]
    async with factory() as session:
        session.add_all(runs)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/evals")

    assert resp.status_code == 200
    code_runs = [r for r in resp.json() if r["dataset_name"] == "code"]
    assert len(code_runs) <= 10


async def test_detect_regressions_with_synthetic_history(test_db):
    """Latest run dropping >= 5% vs prior-window mean is reported."""
    _, factory, _ = test_db
    async with factory() as session:
        for i, score in enumerate([0.82, 0.8, 0.81, 0.79, 0.8], start=1):
            session.add(
                EvalRunModel(
                    id=f"baseline-{i}",
                    dataset_name="book",
                    model_used="ollama/mistral",
                    eval_kind="retrieval",
                    run_at=datetime(2026, 1, i, tzinfo=UTC),
                    hit_rate_5=score,
                    mrr=0.5,
                    faithfulness=0.7,
                )
            )
        session.add(
            EvalRunModel(
                id="current",
                dataset_name="book",
                model_used="ollama/mistral",
                eval_kind="retrieval",
                run_at=datetime(2026, 1, 10, tzinfo=UTC),
                hit_rate_5=0.7,
                mrr=0.5,
                faithfulness=0.7,
            )
        )
        await session.commit()

        regressions = await detect_regressions(session, window=5, threshold_pct=0.05)

    assert len(regressions) == 1
    assert regressions[0].dataset == "book"
    assert regressions[0].metric == "hit_rate_5"
    assert regressions[0].drop_pct >= 0.05


async def test_get_eval_regressions_endpoint(test_db):
    """GET /monitoring/evals/regressions returns detected regression rows."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add_all(
            [
                EvalRunModel(
                    id="old-a",
                    dataset_name="notes",
                    model_used="no-llm",
                    eval_kind="retrieval",
                    run_at=datetime(2026, 1, 1, tzinfo=UTC),
                    mrr=0.6,
                ),
                EvalRunModel(
                    id="new-a",
                    dataset_name="notes",
                    model_used="no-llm",
                    eval_kind="retrieval",
                    run_at=datetime(2026, 1, 2, tzinfo=UTC),
                    mrr=0.5,
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/evals/regressions")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["dataset"] == "notes"
    assert data[0]["metric"] == "mrr"


# GET /monitoring/metrics


async def test_metrics_without_phoenix_still_returns_qa_daily(test_db, monkeypatch):
    """With Phoenix off, metrics returns zero-filled 7-day QA trend and null latencies."""
    _, factory, _ = test_db

    import app.routers.monitoring as mon_module

    async def _not_running() -> bool:
        return False

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _not_running)

    doc = _make_document()
    qa = _make_qa(doc.id, datetime.now(tz=UTC).replace(tzinfo=None))
    async with factory() as session:
        session.add_all([doc, qa])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/metrics")

    assert resp.status_code == 200
    data = resp.json()
    assert data["phoenix_available"] is False
    assert data["latency_p50_ms"] is None
    assert data["error_rate"] is None
    assert data["spans_sampled"] == 0
    assert len(data["qa_daily"]) == 7
    assert data["qa_daily"][-1]["count"] >= 1
    assert sum(d["count"] for d in data["qa_daily"][:-1]) == 0


async def test_metrics_aggregates_span_sample(test_db, monkeypatch):
    """Latency percentiles, error rate, token totals, and kind counts from spans."""
    monkeypatch.setenv("PHOENIX_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.routers.monitoring as mon_module
    from app.routers.monitoring import TraceItem

    def _span(
        i: int,
        kind: str,
        duration: float,
        parent: str | None,
        status: str = "ok",
        attrs: dict | None = None,
    ):
        return TraceItem(
            span_id=f"s{i}",
            trace_id=f"t{i % 3}",
            operation_name=f"op{i}",
            span_kind=kind,
            parent_id=parent,
            start_time="2026-07-09T00:00:00+00:00",
            duration_ms=duration,
            status=status,
            attributes=attrs or {},
        )

    fake_spans = [
        _span(1, "CHAIN", 100.0, None),
        _span(2, "CHAIN", 200.0, None),
        _span(3, "CHAIN", 1000.0, None, status="error"),
        _span(
            4,
            "LLM",
            90.0,
            "s1",
            attrs={"llm.token_count.prompt": 30, "llm.token_count.completion": 10},
        ),
        _span(
            5,
            "LLM",
            190.0,
            "s2",
            attrs={"llm.token_count.prompt": 50, "llm.token_count.completion": 20},
        ),
        _span(6, "RETRIEVER", 15.0, "s1"),
    ]

    async def _running() -> bool:
        return True

    async def _fetch(limit: int = 200):
        return fake_spans

    monkeypatch.setattr(mon_module, "_check_phoenix_running", _running)
    monkeypatch.setattr(mon_module, "_fetch_phoenix_spans", _fetch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/metrics")

    get_settings.cache_clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["phoenix_available"] is True
    assert data["spans_sampled"] == 6
    assert data["traces_sampled"] == 3
    assert data["latency_p50_ms"] == pytest.approx(200.0)
    assert data["latency_p95_ms"] == pytest.approx(1000.0)
    assert data["error_count"] == 1
    assert data["error_rate"] == pytest.approx(1 / 6, abs=1e-3)
    assert data["llm_calls"] == 2
    assert data["llm_prompt_tokens"] == 80
    assert data["llm_completion_tokens"] == 30
    assert data["spans_by_kind"] == {"CHAIN": 3, "LLM": 2, "RETRIEVER": 1}


# GET /monitoring/model-usage


async def test_model_usage_aggregates_call_counts(test_db):
    """GET /monitoring/model-usage returns call count per model from QA history."""
    _, factory, _ = test_db

    doc = _make_document()
    qa_rows = [_make_qa(doc.id, datetime.now(tz=UTC).replace(tzinfo=None)) for _ in range(3)]
    # Override model_used for two of them to create a second model
    qa_rows[2].model_used = "openai/gpt-4o"
    async with factory() as session:
        session.add_all([doc, *qa_rows])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/model-usage")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    models = {row["model"]: row["call_count"] for row in data}
    assert models.get("ollama/llama3", 0) == 2
    assert models.get("openai/gpt-4o", 0) == 1


async def test_model_usage_empty_when_no_qa_history(test_db):
    """GET /monitoring/model-usage returns [] when QA history is empty."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/model-usage")

    assert resp.status_code == 200
    assert resp.json() == []


# S72 — GET /monitoring/phoenix-url


@pytest.mark.asyncio
async def test_phoenix_url_returns_url_and_enabled_flag(test_db, monkeypatch):
    """When Phoenix is enabled and reachable, enabled=true and configured=true."""
    import httpx

    from app.routers import monitoring as mon_module

    # Clear any cached result from previous tests
    mon_module._phoenix_reachability_cache.clear()

    class _FakeResponse:
        status_code = 200

    orig_get = httpx.AsyncClient.get

    # Only intercept the Phoenix health probe; the ASGI test client also
    # goes through httpx.AsyncClient.get.
    async def _fake_get(self, url, **kwargs):
        if ":6006" in str(url):
            return _FakeResponse()
        return await orig_get(self, url, **kwargs)

    monkeypatch.setenv("PHOENIX_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    with unittest.mock.patch.object(httpx.AsyncClient, "get", _fake_get):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/monitoring/phoenix-url")

    get_settings.cache_clear()
    mon_module._phoenix_reachability_cache.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert body["enabled"] is True
    assert body["configured"] is True


@pytest.mark.asyncio
async def test_phoenix_url_disabled_when_unreachable(test_db, monkeypatch):
    """When the Phoenix health check times out, enabled=false but configured=true."""
    import httpx

    from app.routers import monitoring as mon_module

    mon_module._phoenix_reachability_cache.clear()

    orig_get = httpx.AsyncClient.get

    async def _timeout_get(self, url, **kwargs):
        if ":6006" in str(url):
            raise httpx.ConnectError("unreachable")
        return await orig_get(self, url, **kwargs)

    monkeypatch.setenv("PHOENIX_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    with unittest.mock.patch.object(httpx.AsyncClient, "get", _timeout_get):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/monitoring/phoenix-url")

    get_settings.cache_clear()
    mon_module._phoenix_reachability_cache.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert body["enabled"] is False
    assert body["configured"] is True


@pytest.mark.asyncio
async def test_phoenix_url_not_configured(test_db, monkeypatch):
    """When PHOENIX_ENABLED=false, configured=false and no health probe is made."""
    monkeypatch.setenv("PHOENIX_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/monitoring/phoenix-url")

    get_settings.cache_clear()
    body = resp.json()
    assert body["enabled"] is False
    assert body["configured"] is False


@pytest.mark.asyncio
async def test_fetch_phoenix_spans_parses_project_spans_shape(monkeypatch):
    """_fetch_phoenix_spans hits /v1/projects/{project}/spans and maps the 13.x shape."""
    import httpx

    from app.routers import monitoring as mon_module

    seen: dict = {}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "next_cursor": None,
                "data": [
                    {
                        "id": "U3Bhbjox",
                        "name": "qa.stream_answer",
                        "context": {"trace_id": "t1", "span_id": "s1"},
                        "span_kind": "CHAIN",
                        "parent_id": None,
                        "start_time": "2026-07-09T00:00:00+00:00",
                        "end_time": "2026-07-09T00:00:01.500000+00:00",
                        "status_code": "OK",
                        "status_message": "",
                        "attributes": {"input.value": "What is X?"},
                        "events": [],
                    },
                    {
                        "id": "U3Bhbjoy",
                        "name": "retrieval.hybrid",
                        "context": {"trace_id": "t1", "span_id": "s2"},
                        "span_kind": "RETRIEVER",
                        "parent_id": "s1",
                        "start_time": "2026-07-09T00:00:00+00:00",
                        "end_time": "2026-07-09T00:00:00.250000+00:00",
                        "status_code": "UNSET",
                        "status_message": "",
                        "attributes": {},
                        "events": [],
                    },
                ],
            }

    async def _fake_get(self, url, **kwargs):  # noqa: ARG001
        seen["url"] = url
        seen["params"] = kwargs.get("params")
        return _FakeResponse()

    with unittest.mock.patch.object(httpx.AsyncClient, "get", _fake_get):
        items = await mon_module._fetch_phoenix_spans(limit=50)

    assert seen["url"].endswith("/v1/projects/luminary/spans")
    assert seen["params"] == {"limit": 50}
    assert len(items) == 2
    root, child = items
    assert root.span_id == "s1"
    assert root.trace_id == "t1"
    assert root.operation_name == "qa.stream_answer"
    assert root.span_kind == "CHAIN"
    assert root.parent_id is None
    assert root.duration_ms == pytest.approx(1500.0)
    assert root.status == "ok"
    assert child.parent_id == "s1"
    assert child.span_kind == "RETRIEVER"
    assert child.status == "unset"
    assert child.duration_ms == pytest.approx(250.0)
