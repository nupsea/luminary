"""Tests for GET /monitoring/traces and GET /monitoring/overview."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, QAHistoryModel

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GET /monitoring/traces
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GET /monitoring/overview
# ---------------------------------------------------------------------------


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
