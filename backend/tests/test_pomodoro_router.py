"""Integration tests for /pomodoro/* router (S208)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app


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

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# AC1: defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_start_returns_200_with_defaults(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/pomodoro/start", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["focus_minutes"] == 25
    assert body["break_minutes"] == 5
    assert body["surface"] == "none"
    assert body["goal_id"] is None


# ---------------------------------------------------------------------------
# AC2: 409 if active exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_409_when_active_exists(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/pomodoro/start", json={})
        assert first.status_code == 200
        existing_id = first.json()["id"]

        second = await client.post("/pomodoro/start", json={})
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["existing_session_id"] == existing_id


# ---------------------------------------------------------------------------
# AC3: pause / resume cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_then_resume(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post("/pomodoro/start", json={})
        sid = start.json()["id"]

        pause = await client.post(f"/pomodoro/{sid}/pause")
        assert pause.status_code == 200
        assert pause.json()["status"] == "paused"
        assert pause.json()["paused_at"] is not None

        resume = await client.post(f"/pomodoro/{sid}/resume")
        assert resume.status_code == 200
        assert resume.json()["status"] == "active"
        assert resume.json()["paused_at"] is None


# ---------------------------------------------------------------------------
# AC4: complete + AC8: cannot complete twice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_then_double_complete_returns_409(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post("/pomodoro/start", json={})
        sid = start.json()["id"]
        first = await client.post(f"/pomodoro/{sid}/complete")
        assert first.status_code == 200
        assert first.json()["status"] == "completed"
        second = await client.post(f"/pomodoro/{sid}/complete")
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_abandon_sets_status(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post("/pomodoro/start", json={})
        sid = start.json()["id"]
        resp = await client.post(f"/pomodoro/{sid}/abandon")
    assert resp.status_code == 200
    assert resp.json()["status"] == "abandoned"


# ---------------------------------------------------------------------------
# AC5: GET /active 204 when none, payload otherwise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_returns_204_when_none(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/pomodoro/active")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_get_active_returns_session(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post("/pomodoro/start", json={"surface": "read"})
        sid = start.json()["id"]
        resp = await client.get("/pomodoro/active")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid
    assert resp.json()["surface"] == "read"


# ---------------------------------------------------------------------------
# AC6: stats only includes completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_returns_zero_initially(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/pomodoro/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"today_count": 0, "streak_days": 0, "total_completed": 0}


@pytest.mark.asyncio
async def test_stats_counts_only_completed(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Completed once, abandoned once.
        a = await client.post("/pomodoro/start", json={})
        await client.post(f"/pomodoro/{a.json()['id']}/complete")

        b = await client.post("/pomodoro/start", json={})
        await client.post(f"/pomodoro/{b.json()['id']}/abandon")

        resp = await client.get("/pomodoro/stats")
    body = resp.json()
    assert body["total_completed"] == 1
    assert body["today_count"] == 1
    assert body["streak_days"] == 1


@pytest.mark.asyncio
async def test_pause_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/pomodoro/{uuid.uuid4()}/pause")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_focus_minutes_rejected(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/pomodoro/start", json={"focus_minutes": 0})
    assert resp.status_code == 422
