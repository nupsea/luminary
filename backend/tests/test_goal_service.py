"""Tests for GoalService and /goals endpoints."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FlashcardModel
from app.services.goal_service import GoalService, _retrievability

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


def _make_doc(doc_id: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Goal Test Doc",
        format="txt",
        content_type="book",
        word_count=500,
        page_count=10,
        file_path="/tmp/goal_test.txt",
        stage="complete",
    )


def _make_card(
    doc_id: str,
    stability: float = 10.0,
    last_review: datetime | None = None,
) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=None,
        question="What is X?",
        answer="X is Y.",
        source_excerpt="X is Y.",
        fsrs_stability=stability,
        last_review=last_review,
    )


# ---------------------------------------------------------------------------
# Pure function tests: _retrievability
# ---------------------------------------------------------------------------


def test_retrievability_zero_stability_returns_zero():
    assert _retrievability(0.0, 10.0) == 0.0


def test_retrievability_negative_t_returns_zero():
    assert _retrievability(5.0, -1.0) == 0.0


def test_retrievability_at_stability_boundary():
    """At t=0 the formula gives 1.0 (perfect retention)."""
    r = _retrievability(10.0, 0.0)
    assert abs(r - 1.0) < 1e-9


def test_retrievability_decays_over_time():
    r10 = _retrievability(10.0, 10.0)
    r20 = _retrievability(10.0, 20.0)
    assert r10 > r20 > 0.0


def test_retrievability_higher_stability_means_slower_decay():
    r_low = _retrievability(5.0, 10.0)
    r_high = _retrievability(20.0, 10.0)
    assert r_high > r_low


# ---------------------------------------------------------------------------
# GoalService tests
# ---------------------------------------------------------------------------


async def test_create_and_list_goal(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async with factory() as session:
        svc = GoalService(session)
        goal_id = str(uuid.uuid4())
        goal = await svc.create_goal(goal_id, doc_id, "Master the Book", "2026-12-31")
        assert goal.id == goal_id
        assert goal.target_date == "2026-12-31"

        goals = await svc.list_goals()
        assert len(goals) == 1
        assert goals[0].id == goal_id


async def test_delete_goal(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async with factory() as session:
        svc = GoalService(session)
        goal_id = str(uuid.uuid4())
        await svc.create_goal(goal_id, doc_id, "Test Goal", "2026-12-31")

    async with factory() as session:
        svc = GoalService(session)
        deleted = await svc.delete_goal(goal_id)
        assert deleted is True
        goals = await svc.list_goals()
        assert len(goals) == 0


async def test_delete_nonexistent_goal_returns_false(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        svc = GoalService(session)
        deleted = await svc.delete_goal("nonexistent-id")
        assert deleted is False


async def test_compute_readiness_no_cards(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async with factory() as session:
        svc = GoalService(session)
        goal_id = str(uuid.uuid4())
        goal = await svc.create_goal(goal_id, doc_id, "Empty Goal", "2026-12-31")
        result = await svc.compute_readiness(goal)

    assert result["on_track"] is False
    assert result["projected_retention_pct"] == 0.0
    assert result["at_risk_card_count"] == 0


async def test_compute_readiness_high_stability_on_track(test_db):
    """Cards with high stability and a far-future target date should be on track."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    target = (date.today() + timedelta(days=5)).isoformat()

    async with factory() as session:
        session.add(_make_doc(doc_id))
        # Very high stability -> card will be retained
        session.add(_make_card(doc_id, stability=1000.0, last_review=datetime.now(UTC)))
        await session.commit()

    async with factory() as session:
        svc = GoalService(session)
        goal_id = str(uuid.uuid4())
        goal = await svc.create_goal(goal_id, doc_id, "HS Goal", target)
        result = await svc.compute_readiness(goal)

    assert result["on_track"] is True
    assert result["projected_retention_pct"] > 80.0


async def test_compute_readiness_unreviewed_cards_at_risk(test_db):
    """Cards with stability=0 (never reviewed) must appear in at_risk_cards."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    target = (date.today() + timedelta(days=7)).isoformat()

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, stability=0.0, last_review=None))
        await session.commit()

    async with factory() as session:
        svc = GoalService(session)
        goal_id = str(uuid.uuid4())
        goal = await svc.create_goal(goal_id, doc_id, "Unreviewed Goal", target)
        result = await svc.compute_readiness(goal)

    assert result["at_risk_card_count"] == 1
    assert result["at_risk_cards"][0]["projected_retention_pct"] == 0.0


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


async def test_create_goal_endpoint(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/goals",
            json={"document_id": doc_id, "title": "Master X", "target_date": "2026-12-31"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["document_id"] == doc_id
    assert data["title"] == "Master X"
    assert data["target_date"] == "2026-12-31"
    assert "id" in data


async def test_list_goals_endpoint(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/goals",
            json={"document_id": doc_id, "title": "Goal A", "target_date": "2026-06-01"},
        )
        resp = await client.get("/goals")
    assert resp.status_code == 200
    goals = resp.json()
    assert len(goals) >= 1
    assert any(g["title"] == "Goal A" for g in goals)


async def test_delete_goal_endpoint(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/goals",
            json={"document_id": doc_id, "title": "To Delete", "target_date": "2026-12-31"},
        )
        goal_id = create_resp.json()["id"]
        del_resp = await client.delete(f"/goals/{goal_id}")
    assert del_resp.status_code == 204

    async with factory() as session:
        svc = GoalService(session)
        assert await svc.get_goal(goal_id) is None


async def test_readiness_endpoint(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    target = (date.today() + timedelta(days=30)).isoformat()

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_card(doc_id, stability=50.0, last_review=datetime.now(UTC)))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/goals",
            json={"document_id": doc_id, "title": "Readiness Test", "target_date": target},
        )
        goal_id = create_resp.json()["id"]
        resp = await client.get(f"/goals/{goal_id}/readiness")

    assert resp.status_code == 200
    data = resp.json()
    assert "on_track" in data
    assert "projected_retention_pct" in data
    assert "at_risk_card_count" in data
    assert "at_risk_cards" in data
    assert 0.0 <= data["projected_retention_pct"] <= 100.0


async def test_create_goal_invalid_date(test_db):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/goals",
            json={"document_id": doc_id, "title": "Bad Date", "target_date": "not-a-date"},
        )
    assert resp.status_code == 422


async def test_get_readiness_nonexistent_goal(test_db):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/goals/nonexistent-id/readiness")
    assert resp.status_code == 404


async def test_delete_nonexistent_goal_404(test_db):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/goals/nonexistent-id")
    assert resp.status_code == 404
