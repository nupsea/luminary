"""S210: integration tests for /goals router."""

from __future__ import annotations

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
# Create / read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_goal_returns_active(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/goals",
            json={
                "title": "Master Stoicism",
                "goal_type": "recall",
                "target_value": 50,
                "target_unit": "cards",
                "deck_id": "stoicism",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["goal_type"] == "recall"
    assert body["target_value"] == 50
    assert "id" in body


@pytest.mark.asyncio
async def test_post_goal_invalid_type_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/goals", json={"title": "x", "goal_type": "bogus"}
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_goals_status_filter(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        a = await c.post("/goals", json={"title": "A", "goal_type": "read"})
        b = await c.post("/goals", json={"title": "B", "goal_type": "recall"})
        await c.post(f"/goals/{b.json()['id']}/archive")

        active = await c.get("/goals?status=active")
        archived = await c.get("/goals?status=archived")
    assert active.status_code == 200
    assert archived.status_code == 200
    active_ids = {g["id"] for g in active.json()}
    archived_ids = {g["id"] for g in archived.json()}
    assert a.json()["id"] in active_ids
    assert b.json()["id"] in archived_ids
    assert a.json()["id"] not in archived_ids


@pytest.mark.asyncio
async def test_get_goal_by_id(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        created = await c.post("/goals", json={"title": "G", "goal_type": "read"})
        gid = created.json()["id"]
        got = await c.get(f"/goals/{gid}")
    assert got.status_code == 200
    assert got.json()["id"] == gid


@pytest.mark.asyncio
async def test_get_goal_not_found(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/goals/no-such")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Patch / archive / complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_goal_updates_mutable_fields(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        created = await c.post(
            "/goals",
            json={
                "title": "Old",
                "goal_type": "write",
                "target_value": 10,
                "target_unit": "notes",
            },
        )
        gid = created.json()["id"]
        patched = await c.patch(
            f"/goals/{gid}",
            json={"title": "New", "description": "now updated", "target_value": 20},
        )
    assert patched.status_code == 200
    body = patched.json()
    assert body["title"] == "New"
    assert body["description"] == "now updated"
    assert body["target_value"] == 20
    assert body["goal_type"] == "write"  # immutable


@pytest.mark.asyncio
async def test_patch_goal_does_not_change_immutable_fields(test_db):
    """The PATCH schema does not accept goal_type or document_id; even if a
    client posts those keys they are ignored by Pydantic."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        created = await c.post(
            "/goals",
            json={
                "title": "X",
                "goal_type": "write",
                "document_id": "doc-1",
                "deck_id": "deck-1",
            },
        )
        gid = created.json()["id"]
        # Try (uselessly) to mutate goal_type and FK fields.
        await c.patch(
            f"/goals/{gid}",
            json={
                "title": "X2",
                "goal_type": "read",
                "document_id": "doc-2",
                "deck_id": "deck-2",
            },
        )
        got = await c.get(f"/goals/{gid}")
    body = got.json()
    assert body["goal_type"] == "write"
    assert body["document_id"] == "doc-1"
    assert body["deck_id"] == "deck-1"


@pytest.mark.asyncio
async def test_archive_and_complete(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        a = await c.post("/goals", json={"title": "A", "goal_type": "read"})
        archived = await c.post(f"/goals/{a.json()['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        b = await c.post("/goals", json={"title": "B", "goal_type": "read"})
        completed = await c.post(f"/goals/{b.json()['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_archive_unknown_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/goals/no-such/archive")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Sessions linking + delete cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_unlink_session(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post("/goals", json={"title": "g", "goal_type": "read"})
        gid = goal.json()["id"]
        sess = await c.post("/pomodoro/start", json={"surface": "read"})
        sid = sess.json()["id"]

        link = await c.post(f"/goals/{gid}/sessions/{sid}")
        assert link.status_code == 200
        assert link.json()["linked"] is True

        # Verify the pomodoro row reflects the link
        active = await c.get("/pomodoro/active")
        assert active.status_code == 200
        assert active.json()["goal_id"] == gid

        unlink = await c.delete(f"/goals/{gid}/sessions/{sid}")
        assert unlink.status_code == 200
        assert unlink.json()["linked"] is False
        active2 = await c.get("/pomodoro/active")
        assert active2.json()["goal_id"] is None


@pytest.mark.asyncio
async def test_link_unknown_goal_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sess = await c.post("/pomodoro/start", json={})
        sid = sess.json()["id"]
        resp = await c.post(f"/goals/no-such/sessions/{sid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_goal_nulls_linked_sessions(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post("/goals", json={"title": "del", "goal_type": "read"})
        gid = goal.json()["id"]
        sess = await c.post("/pomodoro/start", json={"surface": "read"})
        sid = sess.json()["id"]
        await c.post(f"/goals/{gid}/sessions/{sid}")

        deleted = await c.delete(f"/goals/{gid}")
        assert deleted.status_code == 204

        # Goal gone
        got = await c.get(f"/goals/{gid}")
        assert got.status_code == 404

        # Session persists with goal_id NULL
        active = await c.get("/pomodoro/active")
        assert active.status_code == 200
        assert active.json()["id"] == sid
        assert active.json()["goal_id"] is None


@pytest.mark.asyncio
async def test_delete_unknown_goal_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.delete("/goals/no-such")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Progress endpoint -- shapes per type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_studying_shape(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post(
            "/goals",
            json={
                "title": "Studying",
                "goal_type": "studying",
                "target_value": 60,
                "target_unit": "minutes",
                "collection_id": "collection-1",
            },
        )
        gid = goal.json()["id"]
        resp = await c.get(f"/goals/{gid}/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_id"] == gid
    assert body["goal_type"] == "studying"
    metrics = body["metrics"]
    assert set(metrics.keys()) == {
        "minutes_focused",
        "sessions_completed",
        "surface_minutes",
        "surface_sessions",
        "metadata",
        "completed_pct",
    }
    assert metrics["minutes_focused"] == 0
    assert metrics["sessions_completed"] == 0
    assert metrics["surface_minutes"] == {}
    assert metrics["metadata"]["collection_id"] == "collection-1"


@pytest.mark.asyncio
async def test_get_progress_read_shape(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post(
            "/goals",
            json={
                "title": "Read",
                "goal_type": "read",
                "target_value": 60,
                "target_unit": "minutes",
            },
        )
        gid = goal.json()["id"]
        resp = await c.get(f"/goals/{gid}/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_id"] == gid
    assert body["goal_type"] == "read"
    metrics = body["metrics"]
    assert set(metrics.keys()) == {
        "minutes_focused",
        "sessions_completed",
        "completed_pct",
    }
    assert metrics["minutes_focused"] == 0
    assert metrics["sessions_completed"] == 0


@pytest.mark.asyncio
async def test_get_progress_recall_shape(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post(
            "/goals",
            json={
                "title": "Recall",
                "goal_type": "recall",
                "target_value": 20,
                "target_unit": "cards",
                "deck_id": "stoicism",
            },
        )
        gid = goal.json()["id"]
        resp = await c.get(f"/goals/{gid}/progress")
    metrics = resp.json()["metrics"]
    assert "cards_reviewed" in metrics
    assert "avg_retention" in metrics
    assert "sessions_completed" in metrics


@pytest.mark.asyncio
async def test_get_progress_write_shape(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post(
            "/goals", json={"title": "Write", "goal_type": "write", "target_value": 5}
        )
        gid = goal.json()["id"]
        resp = await c.get(f"/goals/{gid}/progress")
    metrics = resp.json()["metrics"]
    assert "notes_created" in metrics
    assert "sessions_completed" in metrics


@pytest.mark.asyncio
async def test_get_progress_explore_shape(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post(
            "/goals",
            json={"title": "Explore", "goal_type": "explore", "target_value": 5},
        )
        gid = goal.json()["id"]
        resp = await c.get(f"/goals/{gid}/progress")
    metrics = resp.json()["metrics"]
    assert "turns" in metrics
    assert "sessions_completed" in metrics


# ---------------------------------------------------------------------------
# Goalless sessions still count toward /pomodoro/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goalless_session_counts_in_stats(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sess = await c.post("/pomodoro/start", json={})
        sid = sess.json()["id"]
        complete = await c.post(f"/pomodoro/{sid}/complete")
        assert complete.status_code == 200
        assert complete.json()["goal_id"] is None

        stats = await c.get("/pomodoro/stats")
    body = stats.json()
    assert body["total_completed"] == 1
    assert body["today_count"] == 1
    assert body["streak_days"] == 1


# ---------------------------------------------------------------------------
# Linked sessions list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_linked_sessions(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        goal = await c.post("/goals", json={"title": "g", "goal_type": "read"})
        gid = goal.json()["id"]
        sess = await c.post("/pomodoro/start", json={"surface": "read"})
        sid = sess.json()["id"]
        await c.post(f"/goals/{gid}/sessions/{sid}")

        resp = await c.get(f"/goals/{gid}/sessions")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    assert rows[0]["surface"] == "read"
