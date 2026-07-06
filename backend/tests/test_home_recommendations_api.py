from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ConceptModel, FlashcardModel, ReviewEventModel


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


def _naive(days_ago: float = 0.0) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)


async def _seed_due_card(factory) -> None:
    async with factory() as session:
        session.add(
            FlashcardModel(
                id="card-due", question="q", answer="a", source_excerpt="s",
                due_date=_naive(2),
            )
        )
        await session.commit()


async def _seed_weak_concept(factory) -> None:
    async with factory() as session:
        session.add(
            ConceptModel(
                id=str(uuid.uuid4()), slug="btree-splits", label="btree splits",
                mastery=0.2, status="confirmed",
            )
        )
        session.add(
            FlashcardModel(
                id="card-weak", question="q", answer="a", source_excerpt="s",
                concept_slug="btree-splits",
            )
        )
        session.add_all(
            ReviewEventModel(
                id=str(uuid.uuid4()), session_id="s1", flashcard_id="card-weak",
                rating="again", is_correct=False, reviewed_at=_naive(1),
            )
            for _ in range(2)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_overview_hero_carries_recommender_evidence(test_db) -> None:
    _, factory, _ = test_db
    await _seed_due_card(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/home/overview")
        assert resp.status_code == 200
        body = resp.json()
        action = body["today_action"]
        assert action["kind"] == "review_cards"
        assert action["recommendation_id"] is not None
        assert action["reasons"] and action["reasons"][0]["signal"] == "due_cards"
        # hero item is excluded from the secondary stack
        assert all(r["kind"] != "overdue_reviews" for r in body["recommendations"])


@pytest.mark.asyncio
async def test_overview_hero_drill_concept(test_db) -> None:
    _, factory, _ = test_db
    await _seed_weak_concept(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/home/overview")).json()
        action = body["today_action"]
        assert action["kind"] == "drill_concept"
        assert action["target_id"] == "btree-splits"
        assert "mastery 20%" in action["reasons"][0]["detail"]


@pytest.mark.asyncio
async def test_overview_empty_db_degrades_gracefully(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/home/overview")).json()
        assert body["today_action"] is None
        assert body["recommendations"] == []


@pytest.mark.asyncio
async def test_dismiss_endpoint_hides_recommendation(test_db) -> None:
    _, factory, _ = test_db
    await _seed_due_card(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/home/overview")).json()
        rec_id = body["today_action"]["recommendation_id"]

        resp = await client.post(f"/home/recommendations/{rec_id}/dismiss")
        assert resp.status_code == 204

        body = (await client.get("/home/overview")).json()
        assert body["today_action"] is None or body["today_action"]["kind"] != "review_cards"


@pytest.mark.asyncio
async def test_acted_endpoint_and_unknown_id(test_db) -> None:
    _, factory, _ = test_db
    await _seed_due_card(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/home/overview")).json()
        rec_id = body["today_action"]["recommendation_id"]

        assert (await client.post(f"/home/recommendations/{rec_id}/acted")).status_code == 204
        assert (await client.post("/home/recommendations/nope/acted")).status_code == 404
        assert (await client.post("/home/recommendations/nope/dismiss")).status_code == 404
