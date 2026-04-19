"""Tests for GET /study/section-heatmap and _compute_section_heatmap pure function."""

import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, FlashcardModel, SectionModel
from app.routers.study import SectionHeatmapItem, _compute_section_heatmap

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


def _make_section(doc_id: str) -> SectionModel:
    return SectionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        heading="Chapter 1",
        level=1,
        section_order=0,
    )


def _make_chunk(doc_id: str, section_id: str) -> ChunkModel:
    return ChunkModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        section_id=section_id,
        text="Some text content for the chunk.",
        chunk_index=0,
        token_count=50,
    )


def _make_card(
    doc_id: str,
    chunk_id: str,
    fsrs_stability: float = 10.0,
    last_review: datetime | None = None,
    due_date: datetime | None = None,
) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        question="Question?",
        answer="Answer.",
        source_excerpt="Excerpt.",
        fsrs_state="review",
        fsrs_stability=fsrs_stability,
        fsrs_difficulty=3.0,
        due_date=due_date or now + timedelta(days=3),
        reps=3,
        lapses=0,
        last_review=last_review or now - timedelta(days=1),
        created_at=now,
    )


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_heatmap_empty(test_db):
    """No flashcards for document -> heatmap is empty dict."""
    doc_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/section-heatmap?document_id={doc_id}")

    assert resp.status_code == 200
    assert resp.json() == {"heatmap": {}}


@pytest.mark.asyncio
async def test_section_heatmap_high_retrievability_low_fragility(test_db):
    """AC7: card with high retrievability (~0.794) -> fragility_score <= 0.3.

    retrievability = exp(-2.3 / 10) ~= 0.794 -> fragility ~= 0.206
    """
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with factory() as session:
        section = _make_section(doc_id)
        session.add(section)
        await session.flush()

        chunk = _make_chunk(doc_id, section.id)
        session.add(chunk)
        await session.flush()

        # last_review = 2.3 days ago, stability = 10 -> ret = exp(-2.3/10) ~= 0.794
        card = _make_card(
            doc_id=doc_id,
            chunk_id=chunk.id,
            fsrs_stability=10.0,
            last_review=now - timedelta(days=2.3),
        )
        session.add(card)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/section-heatmap?document_id={doc_id}")

    assert resp.status_code == 200
    heatmap = resp.json()["heatmap"]
    assert section.id in heatmap
    item = heatmap[section.id]
    expected_ret = math.exp(-2.3 / 10)
    expected_fragility = 1.0 - expected_ret
    assert abs(item["fragility_score"] - expected_fragility) < 0.01
    assert item["fragility_score"] <= 0.3


@pytest.mark.asyncio
async def test_section_heatmap_null_for_no_cards(test_db):
    """Sections with no associated flashcards do not appear in heatmap."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        # Two sections but only one has a card
        section_a = _make_section(doc_id)
        section_b = _make_section(doc_id)
        session.add(section_a)
        session.add(section_b)
        await session.flush()

        chunk = _make_chunk(doc_id, section_a.id)
        session.add(chunk)
        await session.flush()

        session.add(_make_card(doc_id=doc_id, chunk_id=chunk.id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/section-heatmap?document_id={doc_id}")

    assert resp.status_code == 200
    heatmap = resp.json()["heatmap"]
    assert section_a.id in heatmap
    # section_b has no cards -> absent from heatmap (treated as null by frontend)
    assert section_b.id not in heatmap


@pytest.mark.asyncio
async def test_section_heatmap_due_card_count(test_db):
    """due_card_count reflects cards with due_date <= now."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with factory() as session:
        section = _make_section(doc_id)
        session.add(section)
        await session.flush()

        chunk = _make_chunk(doc_id, section.id)
        session.add(chunk)
        await session.flush()

        # 2 due cards (past), 1 not yet due (future)
        session.add(_make_card(doc_id, chunk.id, due_date=now - timedelta(hours=1)))
        session.add(_make_card(doc_id, chunk.id, due_date=now - timedelta(hours=2)))
        session.add(_make_card(doc_id, chunk.id, due_date=now + timedelta(days=5)))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/section-heatmap?document_id={doc_id}")

    assert resp.status_code == 200
    heatmap = resp.json()["heatmap"]
    assert section.id in heatmap
    assert heatmap[section.id]["due_card_count"] == 2


# ---------------------------------------------------------------------------
# Pure function unit test
# ---------------------------------------------------------------------------


def test_compute_section_heatmap_never_reviewed_card():
    """Card with last_review=None -> retrievability=0, fragility_score=1.0."""
    now = datetime.now(UTC)
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    card = FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        question="Q?",
        answer="A.",
        source_excerpt="Ex.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=0,
        lapses=0,
        last_review=None,  # never reviewed
        created_at=now,
    )

    chunk_to_section = {chunk_id: section_id}
    result = _compute_section_heatmap([card], chunk_to_section, now)

    assert section_id in result
    item = result[section_id]
    assert isinstance(item, SectionHeatmapItem)
    assert item.fragility_score == 1.0
    assert item.avg_retention_pct == 0.0
