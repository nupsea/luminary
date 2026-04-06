"""Tests for SmartTagNormalizerService (S168)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    CanonicalTagModel,
    TagAliasModel,
    TagMergeSuggestionModel,
)
from app.services.tag_normalizer import SmartTagNormalizerService

# ---------------------------------------------------------------------------
# Fixture
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


def _make_tag(tag_id: str, display_name: str, note_count: int = 5) -> CanonicalTagModel:
    return CanonicalTagModel(
        id=tag_id,
        display_name=display_name,
        parent_tag=None,
        note_count=note_count,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Tests: scan
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_scan_creates_suggestion_for_similar_pair(test_db):
    """Scan with similar embeddings creates a TagMergeSuggestionModel row."""
    _engine, factory, _ = test_db

    async with factory() as session:
        session.add(_make_tag("ml", "machine learning", note_count=10))
        session.add(_make_tag("machine-learning", "machine learning", note_count=8))
        await session.commit()

    # ml and machine-learning have identical display_names -> cosine sim = 1.0
    # We mock the embedding service to return near-identical vectors
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.99, 0.14, 0.0], dtype=np.float32)
    # Normalize
    vec_a = vec_a / np.linalg.norm(vec_a)
    vec_b = vec_b / np.linalg.norm(vec_b)
    mock_embeddings = [vec_a.tolist(), vec_b.tolist()]

    service = SmartTagNormalizerService()
    with patch(
        "app.services.tag_normalizer.asyncio.to_thread",
        AsyncMock(return_value=mock_embeddings),
    ):
        async with factory() as session:
            count = await service.scan(session)

    assert count == 1

    async with factory() as session:
        from sqlalchemy import select

        rows = (
            await session.execute(select(TagMergeSuggestionModel))
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "pending"
        assert frozenset([row.tag_a_id, row.tag_b_id]) == frozenset(["ml", "machine-learning"])
        # suggested canonical = tag with higher note_count = "ml" (10)
        assert row.suggested_canonical_id == "ml"


@pytest.mark.anyio
async def test_scan_skips_existing_alias(test_db):
    """Scan skips pairs already linked in TagAliasModel (in either direction)."""
    _engine, factory, _ = test_db

    async with factory() as session:
        session.add(_make_tag("ml", "ml", note_count=10))
        session.add(_make_tag("machine-learning", "machine learning", note_count=8))
        # Pre-existing alias: ml -> machine-learning
        session.add(TagAliasModel(alias="ml", canonical_tag_id="machine-learning"))
        await session.commit()

    vec_a = np.array([1.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.99, 0.14], dtype=np.float32)
    vec_a /= np.linalg.norm(vec_a)
    vec_b /= np.linalg.norm(vec_b)
    mock_embeddings = [vec_a.tolist(), vec_b.tolist()]

    service = SmartTagNormalizerService()
    with patch(
        "app.services.tag_normalizer.asyncio.to_thread",
        AsyncMock(return_value=mock_embeddings),
    ):
        async with factory() as session:
            count = await service.scan(session)

    # Should be skipped because alias already links the pair
    assert count == 0


@pytest.mark.anyio
async def test_scan_skips_pairs_below_threshold(test_db):
    """Scan skips pairs with cosine similarity <= 0.85."""
    _engine, factory, _ = test_db

    async with factory() as session:
        session.add(_make_tag("python", "python", note_count=5))
        session.add(_make_tag("cooking", "cooking", note_count=3))
        await session.commit()

    # Very different vectors -> low similarity
    vec_a = np.array([1.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.0, 1.0], dtype=np.float32)
    mock_embeddings = [vec_a.tolist(), vec_b.tolist()]

    service = SmartTagNormalizerService()
    with patch(
        "app.services.tag_normalizer.asyncio.to_thread",
        AsyncMock(return_value=mock_embeddings),
    ):
        async with factory() as session:
            count = await service.scan(session)

    assert count == 0


@pytest.mark.anyio
async def test_scan_with_fewer_than_two_tags_returns_zero(test_db):
    """Scan with 0 or 1 tags returns 0 without crashing."""
    _engine, factory, _ = test_db

    async with factory() as session:
        session.add(_make_tag("solo", "solo", note_count=1))
        await session.commit()

    service = SmartTagNormalizerService()
    async with factory() as session:
        count = await service.scan(session)

    assert count == 0


# ---------------------------------------------------------------------------
# Tests: accept
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_accept_merges_tags_and_creates_alias(test_db):
    """Accept endpoint creates TagAliasModel and deletes source CanonicalTagModel."""
    _engine, factory, _ = test_db

    async with factory() as session:
        session.add(_make_tag("ml", "ml", note_count=10))
        session.add(_make_tag("machine-learning", "machine learning", note_count=8))
        suggestion = TagMergeSuggestionModel(
            id=str(uuid.uuid4()),
            tag_a_id="machine-learning",
            tag_b_id="ml",
            similarity=0.92,
            suggested_canonical_id="ml",  # ml has higher note_count
            status="pending",
            created_at=datetime.now(UTC),
        )
        session.add(suggestion)
        await session.commit()
        suggestion_id = suggestion.id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/tags/normalization/suggestions/{suggestion_id}/accept"
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "affected_notes" in body
    assert body["affected_notes"] == 0  # no notes had machine-learning tag

    async with factory() as session:
        # Alias created: machine-learning -> ml
        alias = (
            await session.execute(
                select(TagAliasModel).where(TagAliasModel.alias == "machine-learning")
            )
        ).scalar_one_or_none()
        assert alias is not None
        assert alias.canonical_tag_id == "ml"

        # Source canonical tag deleted
        deleted = (
            await session.execute(
                select(CanonicalTagModel).where(CanonicalTagModel.id == "machine-learning")
            )
        ).scalar_one_or_none()
        assert deleted is None

        # Suggestion marked accepted
        sug = (
            await session.execute(
                select(TagMergeSuggestionModel).where(
                    TagMergeSuggestionModel.id == suggestion_id
                )
            )
        ).scalar_one()
        assert sug.status == "accepted"


@pytest.mark.anyio
async def test_reject_sets_status_rejected(test_db):
    """reject_suggestion sets status=rejected without touching tags."""
    _engine, factory, _ = test_db

    async with factory() as session:
        session.add(_make_tag("ai", "ai", note_count=4))
        session.add(_make_tag("artificial-intelligence", "artificial intelligence", note_count=2))
        suggestion = TagMergeSuggestionModel(
            id=str(uuid.uuid4()),
            tag_a_id="ai",
            tag_b_id="artificial-intelligence",
            similarity=0.87,
            suggested_canonical_id="ai",
            status="pending",
            created_at=datetime.now(UTC),
        )
        session.add(suggestion)
        await session.commit()
        suggestion_id = suggestion.id

    service = SmartTagNormalizerService()
    async with factory() as session:
        await service.reject_suggestion(suggestion_id, session)

    async with factory() as session:
        sug = (
            await session.execute(
                select(TagMergeSuggestionModel).where(
                    TagMergeSuggestionModel.id == suggestion_id
                )
            )
        ).scalar_one()
        assert sug.status == "rejected"

        # Tags still exist
        assert (
            await session.execute(select(CanonicalTagModel).where(CanonicalTagModel.id == "ai"))
        ).scalar_one_or_none() is not None
        assert (
            await session.execute(
                select(CanonicalTagModel).where(CanonicalTagModel.id == "artificial-intelligence")
            )
        ).scalar_one_or_none() is not None


