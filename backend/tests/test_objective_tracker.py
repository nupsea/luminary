"""Tests for ObjectiveTrackerService (S143).

Coverage logic: avg(fsrs_stability) of non-definition flashcards in a section.
Threshold: 10.0 days.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    LearningObjectiveModel,
    SectionModel,
)
from app.services.objective_tracker import ObjectiveTrackerService

# ---------------------------------------------------------------------------
# Test DB fixture (same pattern as test_learning.py)
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


def _make_doc(doc_id: str | None = None) -> DocumentModel:
    now = datetime.now(UTC)
    return DocumentModel(
        id=doc_id or str(uuid.uuid4()),
        title="Test Doc",
        format="txt",
        content_type="tech_book",
        word_count=100,
        page_count=1,
        file_path="/tmp/test.txt",
        stage="complete",
        created_at=now,
        last_accessed_at=now,
    )


def _make_section(doc_id: str, section_id: str | None = None) -> SectionModel:
    return SectionModel(
        id=section_id or str(uuid.uuid4()),
        document_id=doc_id,
        heading="Chapter 1",
        level=1,
        section_order=1,
        preview="",
    )


def _make_chunk(doc_id: str, section_id: str) -> ChunkModel:
    now = datetime.now(UTC)
    return ChunkModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        section_id=section_id,
        text="Test chunk",
        token_count=10,
        chunk_index=0,
        created_at=now,
    )


def _make_card(
    doc_id: str,
    chunk_id: str,
    stability: float,
    flashcard_type: str | None = None,
) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        question="Q?",
        answer="A.",
        source_excerpt="...",
        fsrs_state="review",
        fsrs_stability=stability,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=5,
        lapses=0,
        created_at=now,
        flashcard_type=flashcard_type,
    )


def _make_objective(doc_id: str, section_id: str) -> LearningObjectiveModel:
    return LearningObjectiveModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        section_id=section_id,
        text="Understand asyncio",
        covered=False,
    )


# ---------------------------------------------------------------------------
# Unit tests: update_coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_coverage_above_threshold(test_db):
    """Stabilities [5, 12, 18] -> avg=11.67 -> objective covered."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        chunk = _make_chunk(doc_id, section_id)
        session.add(chunk)
        session.add(_make_card(doc_id, chunk.id, 5.0))
        session.add(_make_card(doc_id, chunk.id, 12.0))
        session.add(_make_card(doc_id, chunk.id, 18.0))
        objective = _make_objective(doc_id, section_id)
        session.add(objective)
        await session.commit()
        obj_id = objective.id

    tracker = ObjectiveTrackerService()
    await tracker.update_coverage(doc_id)

    async with factory() as session:
        from sqlalchemy import select

        obj = (
            await session.execute(
                select(LearningObjectiveModel).where(LearningObjectiveModel.id == obj_id)
            )
        ).scalar_one()
        assert obj.covered is True


@pytest.mark.asyncio
async def test_update_coverage_below_threshold(test_db):
    """Stabilities [3, 6, 8] -> avg=5.67 -> objective stays uncovered."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        chunk = _make_chunk(doc_id, section_id)
        session.add(chunk)
        session.add(_make_card(doc_id, chunk.id, 3.0))
        session.add(_make_card(doc_id, chunk.id, 6.0))
        session.add(_make_card(doc_id, chunk.id, 8.0))
        objective = _make_objective(doc_id, section_id)
        session.add(objective)
        await session.commit()
        obj_id = objective.id

    tracker = ObjectiveTrackerService()
    await tracker.update_coverage(doc_id)

    async with factory() as session:
        from sqlalchemy import select

        obj = (
            await session.execute(
                select(LearningObjectiveModel).where(LearningObjectiveModel.id == obj_id)
            )
        ).scalar_one()
        assert obj.covered is False


@pytest.mark.asyncio
async def test_update_coverage_no_flashcards(test_db):
    """No flashcards in section -> objective stays uncovered."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        objective = _make_objective(doc_id, section_id)
        session.add(objective)
        await session.commit()
        obj_id = objective.id

    tracker = ObjectiveTrackerService()
    await tracker.update_coverage(doc_id)

    async with factory() as session:
        from sqlalchemy import select

        obj = (
            await session.execute(
                select(LearningObjectiveModel).where(LearningObjectiveModel.id == obj_id)
            )
        ).scalar_one()
        assert obj.covered is False


@pytest.mark.asyncio
async def test_update_coverage_excludes_definition_type(test_db):
    """Definition-type flashcards are excluded; avg of remaining below threshold stays uncovered."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        chunk = _make_chunk(doc_id, section_id)
        session.add(chunk)
        # High-stability definition card that would tip the average above threshold
        session.add(_make_card(doc_id, chunk.id, 100.0, flashcard_type="definition"))
        # Low-stability non-definition card
        session.add(_make_card(doc_id, chunk.id, 4.0, flashcard_type="application"))
        objective = _make_objective(doc_id, section_id)
        session.add(objective)
        await session.commit()
        obj_id = objective.id

    tracker = ObjectiveTrackerService()
    await tracker.update_coverage(doc_id)

    async with factory() as session:
        from sqlalchemy import select

        obj = (
            await session.execute(
                select(LearningObjectiveModel).where(LearningObjectiveModel.id == obj_id)
            )
        ).scalar_one()
        # avg([4.0]) = 4.0 < 10.0 -> not covered
        assert obj.covered is False


@pytest.mark.asyncio
async def test_get_progress_returns_correct_totals(test_db):
    """get_progress returns accurate total/covered counts and progress_pct."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        # 2 objectives, 1 pre-covered
        obj1 = LearningObjectiveModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section_id,
            text="Obj 1",
            covered=True,
        )
        obj2 = LearningObjectiveModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section_id,
            text="Obj 2",
            covered=False,
        )
        session.add(obj1)
        session.add(obj2)
        await session.commit()

    tracker = ObjectiveTrackerService()
    result = await tracker.get_progress(doc_id)

    assert result["total_objectives"] == 2
    assert result["covered_objectives"] == 1
    assert result["progress_pct"] == 50.0
    assert len(result["by_chapter"]) == 1
    assert result["by_chapter"][0]["total_objectives"] == 2
    assert result["by_chapter"][0]["covered_objectives"] == 1


@pytest.mark.asyncio
async def test_get_progress_no_objectives(test_db):
    """get_progress returns zeros when document has no objectives."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    tracker = ObjectiveTrackerService()
    result = await tracker.get_progress(doc_id)

    assert result["total_objectives"] == 0
    assert result["covered_objectives"] == 0
    assert result["progress_pct"] == 0.0
    assert result["by_chapter"] == []


# ---------------------------------------------------------------------------
# Integration tests: API endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_endpoint(test_db):
    """GET /documents/{id}/progress returns 200 with correct schema."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        session.add(_make_objective(doc_id, section_id))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/documents/{doc_id}/progress")

    assert resp.status_code == 200
    data = resp.json()
    assert "total_objectives" in data
    assert "by_chapter" in data
    assert data["total_objectives"] == 1


@pytest.mark.asyncio
async def test_get_progress_endpoint_no_objectives(test_db):
    """GET /documents/{id}/progress returns zeros for docs without objectives."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/documents/{doc_id}/progress")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_objectives"] == 0
    assert data["progress_pct"] == 0.0


@pytest.mark.asyncio
async def test_refresh_progress_endpoint(test_db):
    """POST /documents/{id}/refresh_progress triggers update and returns progress."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_section(doc_id, section_id))
        chunk = _make_chunk(doc_id, section_id)
        session.add(chunk)
        # Cards with avg stability above threshold
        session.add(_make_card(doc_id, chunk.id, 15.0))
        session.add(_make_card(doc_id, chunk.id, 20.0))
        session.add(_make_objective(doc_id, section_id))
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(f"/documents/{doc_id}/refresh_progress")

    assert resp.status_code == 200
    data = resp.json()
    assert data["covered_objectives"] == 1
    assert data["progress_pct"] == 100.0


@pytest.mark.asyncio
async def test_progress_endpoint_404(test_db):
    """GET /documents/{id}/progress returns 404 for unknown document."""
    _, _factory, _ = test_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/documents/{uuid.uuid4()}/progress")

    assert resp.status_code == 404
