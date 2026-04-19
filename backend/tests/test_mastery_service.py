"""Unit tests for MasteryService (S145).

AC1: compute_mastery formula with bloom_level weighting and prediction error penalty
AC2: bloom_level 4-5 weighted higher than 1-2 for same stabilities
AC3: prediction error (correct=False) reduces mastery by 0.05
AC4: GapReport gains 'weak' field; concepts with mastery < 0.3 appear in 'weak'
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    NoteModel,
    PredictionEventModel,
)
from app.services.mastery_service import MasteryService

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


def _make_doc(doc_id: str, suffix: str = "") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=f"Test Book{suffix}",
        format="txt",
        content_type="tech_book",
        page_count=10,
        file_path=f"/tmp/t{suffix}.pdf",
        stage="complete",
    )


def _make_chunk(chunk_id: str, doc_id: str, text: str) -> ChunkModel:
    return ChunkModel(
        id=chunk_id,
        document_id=doc_id,
        section_id=None,
        text=text,
        token_count=len(text.split()),
        chunk_index=0,
    )


def _make_card(
    doc_id: str,
    chunk_id: str,
    stability: float,
    bloom: int | None,
) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_id,
        source="document",
        deck="default",
        question="Q?",
        answer="A.",
        source_excerpt="excerpt",
        difficulty="medium",
        fsrs_stability=stability,
        bloom_level=bloom,
    )


# ---------------------------------------------------------------------------
# Pure function unit tests: _compute_weighted_mastery
# ---------------------------------------------------------------------------


def test_compute_weighted_mastery_bloom_high_vs_low(test_db):
    """AC2: Mixed bloom levels -- high bloom cards (4-5) weighted 1.5x.

    Stabilities [7, 14, 21], set A has bloom [2, 4, 5], set B has bloom [1, 1, 2].
    Set A gives higher mastery because the high-stability card (21) has bloom=5 (1.5x).
    Set B treats all cards equally (weight=1.0) so mastery = arithmetic mean.
    """
    svc = MasteryService()
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    # Set A: bloom [2, 4, 5] -- card at stab=21 has 1.5x weight
    cards_high = [
        _make_card(doc_id, chunk_id, 7.0, 2),
        _make_card(doc_id, chunk_id, 14.0, 4),
        _make_card(doc_id, chunk_id, 21.0, 5),
    ]
    # Set B: bloom [1, 1, 2] -- all cards weight=1.0
    cards_low = [
        _make_card(doc_id, chunk_id, 7.0, 1),
        _make_card(doc_id, chunk_id, 14.0, 1),
        _make_card(doc_id, chunk_id, 21.0, 2),
    ]

    mastery_high = svc._compute_weighted_mastery(cards_high)
    mastery_low = svc._compute_weighted_mastery(cards_low)

    # Set A: (1.0*1/3 + 1.5*2/3 + 1.5*1.0) / (1.0+1.5+1.5) = 2.833/4.0 = 0.708
    # Set B: (1/3 + 2/3 + 1.0) / 3.0 = 2.0/3.0 = 0.667
    assert mastery_high > mastery_low, (
        f"High bloom mastery {mastery_high} should exceed low bloom {mastery_low}"
    )


def test_compute_weighted_mastery_empty(test_db):
    """Returns 0.0 when no cards."""
    svc = MasteryService()
    assert svc._compute_weighted_mastery([]) == 0.0


def test_compute_weighted_mastery_capped(test_db):
    """fsrs_stability >= 21 yields 1.0 contribution (capped)."""
    svc = MasteryService()
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    cards = [_make_card(doc_id, chunk_id, 100.0, 1)]  # way above cap
    assert svc._compute_weighted_mastery(cards) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Integration tests: compute_mastery against real SQLite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_mastery_no_flashcards(test_db):
    """AC1: concept with no matching chunks returns no_flashcards=True, mastery=0.0."""
    _engine, factory, _tmp = test_db
    svc = MasteryService()
    doc_id = str(uuid.uuid4())

    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        async with factory() as session:
            result = await svc.compute_mastery("closures", [doc_id], session)

    assert result.no_flashcards is True
    assert result.mastery == 0.0
    assert result.card_count == 0


@pytest.mark.asyncio
async def test_compute_mastery_prediction_error_reduces_mastery(test_db):
    """AC3: correct=False PredictionEventModel reduces mastery by 0.05."""
    _engine, factory, _tmp = test_db
    svc = MasteryService()
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id, "Python closures capture variables"))
        session.add(_make_card(doc_id, chunk_id, 14.0, 2))
        await session.commit()

    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        async with factory() as session:
            result_no_error = await svc.compute_mastery("closures", [doc_id], session)

    # Add a prediction error
    async with factory() as session:
        session.add(
            PredictionEventModel(
                id=str(uuid.uuid4()),
                chunk_id=chunk_id,
                document_id=doc_id,
                code_content="def f(): pass",
                expected="1",
                actual="2",
                correct=False,
                language="python",
            )
        )
        await session.commit()

    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        async with factory() as session:
            result_with_error = await svc.compute_mastery("closures", [doc_id], session)

    # With 1 error, penalty = 0.05
    assert result_with_error.mastery == pytest.approx(result_no_error.mastery - 0.05, abs=1e-6)


@pytest.mark.asyncio
async def test_compute_mastery_prediction_error_capped(test_db):
    """Prediction error penalty is capped at 0.20 regardless of error count."""
    _engine, factory, _tmp = test_db
    svc = MasteryService()
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, "2"))
        session.add(_make_chunk(chunk_id, doc_id, "generators in python yield lazily"))
        session.add(_make_card(doc_id, chunk_id, 21.0, 1))  # stability=21 -> mastery=1.0
        # 10 prediction errors -- penalty should be capped at 0.20
        for _ in range(10):
            session.add(
                PredictionEventModel(
                    id=str(uuid.uuid4()),
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    code_content="def g(): yield",
                    expected="1",
                    actual="2",
                    correct=False,
                    language="python",
                )
            )
        await session.commit()

    with patch("app.services.mastery_service.get_graph_service") as mock_graph_factory:
        mock_graph = MagicMock()
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        async with factory() as session:
            result = await svc.compute_mastery("generators", [doc_id], session)

    # 1.0 - capped(10 * 0.05 -> max 0.20) = 0.80
    assert result.mastery == pytest.approx(0.80, abs=1e-6)


@pytest.mark.asyncio
async def test_gap_report_weak_field(test_db):
    """AC4: detect_gaps returns weak list; covered concept with mastery < 0.3 in weak."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id, "3"))
        session.add(_make_chunk(chunk_id, doc_id, "decorator pattern in python"))
        # Low-stability card -> mastery = 1/21 ~ 0.048 (well below 0.3)
        session.add(_make_card(doc_id, chunk_id, 1.0, 2))
        session.add(
            NoteModel(
                id=note_id,
                document_id=doc_id,
                content="decorator pattern in python",
            )
        )
        await session.commit()

    llm_response_text = '{"gaps": [], "covered": ["decorator"]}'

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = llm_response_text

    async def fake_acompletion(*args, **kwargs):
        return mock_response

    async def fake_retrieve(*args, **kwargs):
        return []

    with (
        patch(
            "app.services.gap_detector.litellm.acompletion",
            side_effect=fake_acompletion,
        ),
        patch("app.services.mastery_service.get_graph_service") as mock_graph_factory,
        patch("app.services.retriever.get_retriever") as mock_retriever_factory,
    ):
        mock_graph = MagicMock()
        mock_graph.get_concept_clusters.return_value = []
        mock_graph_factory.return_value = mock_graph

        mock_retriever = MagicMock()
        mock_retriever.retrieve = fake_retrieve
        mock_retriever_factory.return_value = mock_retriever

        from app.services.gap_detector import GapDetectorService

        async with factory() as session:
            svc = GapDetectorService()
            report = await svc.detect_gaps([note_id], doc_id, session=session)

    assert "weak" in report
    assert "decorator" in report["weak"], (
        f"'decorator' should appear in weak list; got {report['weak']}"
    )
