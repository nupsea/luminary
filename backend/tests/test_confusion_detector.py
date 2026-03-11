"""Tests for S100: ConfusionDetectorService and GET /chat/confusion-signals.

Covers:
  (a) test_detect_returns_signal_above_threshold: 4 rows with 'entanglement' -> signal count=4
  (b) test_detect_below_threshold_returns_empty: 2 rows -> []
  (c) test_detect_ignores_stopwords: only non-stopword 'alice' found; no stopwords in results
  (d) test_detect_lookback_respected: rows outside window not counted
  (e) test_confusion_api_returns_list: GET /chat/confusion-signals returns HTTP 200 + JSON array
"""

import uuid
from datetime import UTC, datetime, timedelta

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
# Async in-memory SQLite fixture for service unit tests
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


# ---------------------------------------------------------------------------
# (a) Signal returned above threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_returns_signal_above_threshold(db_session):
    """4 rows each containing 'entanglement' -> ConfusionSignal concept='entanglement', count=4."""
    for _ in range(4):
        db_session.add(_qa_row("what is quantum entanglement exactly"))
    await db_session.commit()

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
    """Only 2 rows -> [] (total rows < threshold=3)."""
    for _ in range(2):
        db_session.add(_qa_row("what is quantum entanglement"))
    await db_session.commit()

    svc = ConfusionDetectorService()
    signals = await svc.detect(db_session, threshold=3)
    assert signals == []


# ---------------------------------------------------------------------------
# (c) Stopwords are ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_ignores_stopwords(db_session):
    """Stopwords must not appear in results; 'alice' (non-stopword) should be found."""
    # Insert 4 rows -- each has 'alice' and stopwords
    for _ in range(4):
        db_session.add(_qa_row("what is alice about in the book"))
    await db_session.commit()

    svc = ConfusionDetectorService()
    signals = await svc.detect(db_session, threshold=3)

    concepts = {s["concept"] for s in signals}
    assert "alice" in concepts

    from app.services.confusion_detector import _STOPWORDS
    for concept in concepts:
        assert concept not in _STOPWORDS, f"Stopword '{concept}' appeared in signals"


# ---------------------------------------------------------------------------
# (d) Lookback window respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_lookback_respected(db_session):
    """Rows older than lookback window are excluded; 2 recent + 3 old -> [] (total recent < 3)."""
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
# (e) API endpoint returns HTTP 200 and JSON array
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
