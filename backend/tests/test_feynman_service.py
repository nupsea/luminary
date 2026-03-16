"""Unit tests for FeynmanService (S144).

AC3: complete_session() with 2 identified gaps generates >= 2 flashcards
     with source='feynman' and flashcard_type='concept_explanation'.
AC4: tutor prompt includes section summary content in system context.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    FeynmanSessionModel,
    FeynmanTurnModel,
    FlashcardModel,
    SectionSummaryModel,
)
from app.services.feynman_service import (
    FeynmanService,
    _parse_gaps,
    _strip_gaps_block,
)


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
# Pure function unit tests
# ---------------------------------------------------------------------------


def test_parse_gaps_extracts_list():
    raw = 'Good attempt. You missed the key part.\ngaps: ["lexical scope", "closure captures by reference"]'
    result = _parse_gaps(raw)
    assert result == ["lexical scope", "closure captures by reference"]


def test_parse_gaps_empty_list():
    raw = "Great explanation!\ngaps: []"
    assert _parse_gaps(raw) == []


def test_parse_gaps_missing_block():
    raw = "Good job, you covered everything!"
    assert _parse_gaps(raw) == []


def test_strip_gaps_block():
    raw = "Excellent work!\ngaps: [\"closure\"]"
    stripped = _strip_gaps_block(raw)
    assert "gaps:" not in stripped
    assert "Excellent work!" in stripped


# ---------------------------------------------------------------------------
# AC3: complete_session() with 2 gaps generates >= 2 feynman flashcards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_session_generates_feynman_flashcards(test_db):
    """AC3: complete_session with 2 gaps creates >= 2 flashcards with source='feynman'."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    # Mock LLM response for flashcard generation
    gap_flashcard_response = '{"front": "What is lexical scope?", "back": "Scope defined at definition time."}'

    async with factory() as session:
        # Create session row
        feynman_session = FeynmanSessionModel(
            id=session_id,
            document_id=doc_id,
            section_id=None,
            concept="closures",
            status="active",
        )
        session.add(feynman_session)

        # Add two tutor turns with gaps identified
        turn1 = FeynmanTurnModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_index=0,
            role="tutor",
            content="Explain closures.\ngaps: []",
            gaps_identified=[],
        )
        turn2 = FeynmanTurnModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_index=2,
            role="tutor",
            content='Good. You missed some things.\ngaps: ["lexical scope", "reference capture"]',
            gaps_identified=["lexical scope", "reference capture"],
        )
        session.add(turn1)
        session.add(turn2)
        await session.commit()

    svc = FeynmanService()

    with patch(
        "app.services.feynman_service.get_feynman_service",
        return_value=svc,
    ):
        with patch("app.services.flashcard.get_llm_service") as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(return_value=gap_flashcard_response)
            mock_llm_factory.return_value = mock_llm

            async with factory() as session:
                result = await svc.complete_session(session_id, session)

    assert result["gap_count"] >= 2
    assert len(result["flashcard_ids"]) >= 2

    # Verify flashcard rows in DB
    async with factory() as session:
        rows = (
            await session.execute(
                select(FlashcardModel).where(
                    FlashcardModel.document_id == doc_id,
                    FlashcardModel.source == "feynman",
                )
            )
        ).scalars().all()

    assert len(rows) >= 2
    for card in rows:
        assert card.source == "feynman"
        assert card.flashcard_type == "concept_explanation"
        assert card.deck == "feynman"


# ---------------------------------------------------------------------------
# AC4: tutor prompt includes section summary content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_system_prompt_includes_section_summary(test_db):
    """AC4: section summary content appears in the LLM system prompt."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    unique_content = f"UNIQUE_SUMMARY_CONTENT_{uuid.uuid4().hex[:8]}"

    async with factory() as session:
        summary = SectionSummaryModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section_id,
            heading="Chapter 1",
            content=unique_content,
            unit_index=0,
        )
        session.add(summary)
        await session.commit()

    svc = FeynmanService()
    captured_systems: list[str] = []

    async def capturing_generate(prompt, system="", stream=False, model=None):
        captured_systems.append(system)
        return "Please explain closures as if teaching a beginner."

    with patch("app.services.feynman_service.get_llm_service") as mock_llm_factory:
        mock_llm = AsyncMock()
        mock_llm.generate = capturing_generate
        mock_llm_factory.return_value = mock_llm

        async with factory() as session:
            _session_row, _opening = await svc.create_session(
                document_id=doc_id,
                section_id=section_id,
                concept="closures",
                session=session,
            )

    # The system prompt passed to LLM must contain the section summary content
    assert len(captured_systems) == 1
    assert unique_content in captured_systems[0], (
        f"Expected section summary content in system prompt. "
        f"Got: {captured_systems[0][:200]}"
    )
