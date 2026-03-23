"""Tests for StudyPathService pure functions and FSRS skip logic (S139).

Unit tests (AC3):
  - test_compute_mastery_empty: empty list returns 0.0
  - test_compute_mastery_caps_at_one: stabilities >= 21 cap at 1.0
  - test_compute_mastery_partial: partial stability < 21 gives < 1.0
  - test_should_skip_true: avg_stability >= 14 -> True
  - test_should_skip_false: avg_stability < 14 -> False
  - test_should_skip_exactly_at_threshold: 14.0 -> True
  - test_build_skip_reason: formats reason string correctly
  - test_study_path_skip_stable_concept: FSRS integration test
"""

import uuid

import pytest

from app.services.study_path_service import (
    build_skip_reason,
    compute_mastery,
    should_skip,
)

# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_compute_mastery_empty():
    """Empty stability list returns 0.0."""
    assert compute_mastery([]) == pytest.approx(0.0)


def test_compute_mastery_caps_at_one():
    """Stabilities >= 21.0 days cap mastery at 1.0."""
    assert compute_mastery([21.0]) == pytest.approx(1.0)
    assert compute_mastery([21.0, 30.0]) == pytest.approx(1.0)
    assert compute_mastery([42.0]) == pytest.approx(1.0)


def test_compute_mastery_partial():
    """Stability < 21.0 gives mastery < 1.0."""
    result = compute_mastery([10.5])
    assert 0.0 < result < 1.0
    assert result == pytest.approx(10.5 / 21.0)


def test_compute_mastery_average():
    """Multiple stability values are averaged."""
    result = compute_mastery([7.0, 14.0])  # avg = 10.5
    assert result == pytest.approx(10.5 / 21.0)


def test_should_skip_true():
    """avg_stability >= 14 returns True."""
    assert should_skip(14.0) is True
    assert should_skip(20.0) is True
    assert should_skip(100.0) is True


def test_should_skip_false():
    """avg_stability < 14 returns False."""
    assert should_skip(13.9) is False
    assert should_skip(0.0) is False
    assert should_skip(7.0) is False


def test_should_skip_exactly_at_threshold():
    """avg_stability == 14.0 exactly returns True (>= threshold)."""
    assert should_skip(14.0) is True


def test_build_skip_reason():
    """Reason string format is correct."""
    assert build_skip_reason(18.0) == "avg_stability=18d"
    assert build_skip_reason(14.0) == "avg_stability=14d"
    # Rounds to 0 decimal places
    result = build_skip_reason(14.5)
    assert result in ("avg_stability=14d", "avg_stability=15d")


def test_should_skip_custom_threshold():
    """Custom threshold is respected."""
    assert should_skip(9.0, threshold=10.0) is False
    assert should_skip(10.0, threshold=10.0) is True


# ---------------------------------------------------------------------------
# Integration test: get_study_path skip logic (AC3)
# ---------------------------------------------------------------------------


async def test_study_path_skip_stable_concept(tmp_path, monkeypatch):
    """AC3: concept with avg_stability >= 14 days gets skip=True, reason='avg_stability=Xd'.

    Sets up:
    - Kuzu with PREREQUISITE_OF edge: decorators -> closures
    - SQLite with FlashcardModel for 'closures' (fsrs_stability=20.0, reps=1)
    - Calls StudyPathService.get_study_path(doc_id, 'decorators', session)
    - Asserts path item for 'closures' has skip=True
    """
    import os

    import app.database as db_module
    import app.services.graph as graph_module

    os.environ["DATA_DIR"] = str(tmp_path)
    from app.config import get_settings

    get_settings.cache_clear()
    graph_module._graph_service = None

    from app.database import make_engine

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sm = async_sessionmaker(engine, expire_on_commit=False)
    db_module._engine = engine
    db_module._session_factory = sm

    from app.db_init import create_all_tables

    await create_all_tables(engine)

    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    # Seed graph
    from app.services.graph import get_graph_service

    gv = get_graph_service()
    gv.upsert_document(doc_id, "Python Tutorial", "tech_book")

    closures_id = str(uuid.uuid4())
    decorators_id = str(uuid.uuid4())
    gv.upsert_entity(closures_id, "closures", "CONCEPT")
    gv.upsert_entity(decorators_id, "decorators", "CONCEPT")
    gv.add_mention(closures_id, doc_id)
    gv.add_mention(decorators_id, doc_id)

    # decorators requires closures
    gv.add_prerequisite(decorators_id, closures_id, doc_id, confidence=0.9)

    # Seed chunk and flashcard for 'closures'

    from app.models import ChunkModel, FlashcardModel

    async with sm() as session:
        chunk = ChunkModel(
            id=chunk_id,
            document_id=doc_id,
            text="This section covers closures in Python.",
            token_count=10,
            chunk_index=0,
        )
        session.add(chunk)
        card = FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            chunk_id=chunk_id,
            question="What is a closure?",
            answer="A function that captures its surrounding scope.",
            source_excerpt="closures in Python",
            fsrs_stability=20.0,  # >= 14 -> should skip
            fsrs_difficulty=0.0,
            fsrs_state="review",
            reps=1,
            lapses=0,
        )
        session.add(card)
        await session.commit()

    # Run StudyPathService
    from app.services.study_path_service import StudyPathService

    svc = StudyPathService()
    async with sm() as session:
        result = await svc.get_study_path(doc_id, "decorators", session)

    # Find the 'closures' path item
    path = result["path"]
    assert len(path) >= 1, f"Expected path items, got: {path}"

    closures_item = next((p for p in path if "closures" in p.concept.lower()), None)
    assert closures_item is not None, (
        f"Expected 'closures' in path. Got concepts: {[p.concept for p in path]}"
    )
    assert closures_item.skip is True, (
        f"Expected skip=True for concept with avg_stability=20d, got skip={closures_item.skip}"
    )
    assert "avg_stability" in closures_item.reason, (
        f"Expected reason to contain 'avg_stability', got: {closures_item.reason}"
    )
