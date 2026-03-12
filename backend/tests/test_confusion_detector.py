"""Tests for S100: ConfusionDetectorService and GET /chat/confusion-signals.

Covers:
  (a) test_detect_returns_signal_above_threshold: 4 questions with 'entanglement' -> signal count=4
  (b) test_detect_below_threshold_returns_empty: 2 rows -> [] (early return, no GLiNER call)
  (c) test_detect_counts_distinct_questions: entity in 3 questions, twice in 1 -> count=3 not 4
  (d) test_detect_lookback_respected: old rows excluded by WHERE cutoff; 2 recent < threshold -> []
  (e) test_detect_gliner_failure_returns_empty: extract() raises -> [] gracefully
  (f) test_confusion_api_returns_list: GET /chat/confusion-signals returns HTTP 200 + JSON array
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_init import create_all_tables
from app.main import app
from app.models import QAHistoryModel
from app.services.confusion_detector import ConfusionDetectorService

# Capture "now" once at module load so all rows use a consistent reference point.
_NOW = datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _qa_row(question: str, days_ago: int = 0) -> QAHistoryModel:
    return QAHistoryModel(
        id=str(uuid.uuid4()),
        document_id=None,
        scope="all",
        question=question,
        answer="some answer",
        citations=[],
        confidence="medium",
        model_used="ollama/test",
        created_at=_NOW - timedelta(days=days_ago),
    )


def _entity(name: str, chunk_id: str, etype: str = "CONCEPT") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": etype,
        "chunk_id": chunk_id,
        "document_id": "__confusion_detection__",
    }


# ---------------------------------------------------------------------------
# (a) Signal returned above threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_returns_signal_above_threshold(db_session):
    """4 questions each about 'entanglement' -> ConfusionSignal concept='entanglement', count=4."""
    for _ in range(4):
        db_session.add(_qa_row("what is quantum entanglement exactly"))
    await db_session.commit()

    def mock_extract(chunks, content_type=None):
        return [_entity("entanglement", c["id"]) for c in chunks]

    mock_extractor = MagicMock()
    mock_extractor.extract.side_effect = mock_extract

    with patch("app.services.confusion_detector.get_entity_extractor", return_value=mock_extractor):
        svc = ConfusionDetectorService()
        signals = await svc.detect(db_session, threshold=3)

    assert len(signals) >= 1
    concepts = {s["concept"] for s in signals}
    assert "entanglement" in concepts
    entanglement_signal = next(s for s in signals if s["concept"] == "entanglement")
    assert entanglement_signal["count"] == 4


# ---------------------------------------------------------------------------
# (b) Below threshold returns empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_below_threshold_returns_empty(db_session):
    """Only 2 rows -> [] because total rows < threshold=3 (early return, GLiNER not called)."""
    for _ in range(2):
        db_session.add(_qa_row("what is quantum entanglement"))
    await db_session.commit()

    svc = ConfusionDetectorService()
    signals = await svc.detect(db_session, threshold=3)
    assert signals == []


# ---------------------------------------------------------------------------
# (c) Distinct question counting -- not raw entity mention count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_counts_distinct_questions(db_session):
    """Entity mentioned twice in one question and once each in two others -> count=3, not 4.

    This is the key correctness invariant: confusion is 'asked about concept across N
    different questions', not 'concept mentioned N times total'.
    """
    for _ in range(3):
        db_session.add(_qa_row("what is entanglement"))
    await db_session.commit()

    def mock_extract(chunks, content_type=None):
        entities = []
        for i, c in enumerate(chunks):
            entities.append(_entity("entanglement", c["id"]))
            if i == 0:
                # Duplicate mention in the first question -- must not inflate the count.
                entities.append(_entity("entanglement", c["id"]))
        return entities

    mock_extractor = MagicMock()
    mock_extractor.extract.side_effect = mock_extract

    with patch("app.services.confusion_detector.get_entity_extractor", return_value=mock_extractor):
        svc = ConfusionDetectorService()
        signals = await svc.detect(db_session, threshold=3)

    assert len(signals) == 1
    assert signals[0]["concept"] == "entanglement"
    assert signals[0]["count"] == 3


# ---------------------------------------------------------------------------
# (d) Lookback window respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_lookback_respected(db_session):
    """Rows older than lookback window are excluded; 2 recent + 3 old -> [] (2 < threshold=3)."""
    # 2 recent rows
    for _ in range(2):
        db_session.add(_qa_row("all about quasar phenomena", days_ago=5))
    # 3 old rows (outside 30-day window)
    for _ in range(3):
        db_session.add(_qa_row("all about quasar phenomena", days_ago=40))
    await db_session.commit()

    svc = ConfusionDetectorService()
    signals = await svc.detect(db_session, lookback_days=30, threshold=3)
    assert signals == []


# ---------------------------------------------------------------------------
# (e) GLiNER failure returns empty list gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_gliner_failure_returns_empty(db_session):
    """If GLiNER extract() raises, detect() logs a warning and returns []."""
    for _ in range(4):
        db_session.add(_qa_row("what is quantum entanglement"))
    await db_session.commit()

    mock_extractor = MagicMock()
    mock_extractor.extract.side_effect = RuntimeError("GLiNER unavailable")

    with patch("app.services.confusion_detector.get_entity_extractor", return_value=mock_extractor):
        svc = ConfusionDetectorService()
        signals = await svc.detect(db_session, threshold=3)

    assert signals == []


# ---------------------------------------------------------------------------
# (f) API endpoint returns HTTP 200 and JSON array
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_confusion_api_returns_list(client):
    """GET /chat/confusion-signals returns HTTP 200 and a JSON array."""
    resp = client.get("/chat/confusion-signals")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
