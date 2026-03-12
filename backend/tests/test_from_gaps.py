"""Tests for S97: POST /flashcards/from-gaps endpoint.

Test plan:
  1. test_from_gaps_api_422_empty_gaps        -- API: empty gaps list returns 422
  2. test_from_gaps_api_empty_document_id_allowed -- API: document_id='' is valid
  3. test_generate_from_gaps_creates_flashcards   -- unit: service creates one card per valid gap
  4. test_generate_from_gaps_skips_malformed_llm  -- unit: service skips unparseable LLM responses
  5. test_from_gaps_api_503_ollama_offline         -- API: Ollama offline returns 503
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# API boundary tests
# ---------------------------------------------------------------------------


def test_from_gaps_api_422_empty_gaps(client):
    """POST /flashcards/from-gaps with empty gaps list returns 422."""
    resp = client.post("/flashcards/from-gaps", json={"gaps": [], "document_id": ""})
    assert resp.status_code == 422


def test_from_gaps_api_empty_document_id_allowed(client):
    """POST /flashcards/from-gaps with document_id='' is accepted (no min_length)."""
    mock_llm = AsyncMock(
        return_value='{"front": "What is time travel?", "back": "Moving through time"}'
    )
    with patch("app.services.llm.LLMService.generate", mock_llm):
        resp = client.post(
            "/flashcards/from-gaps",
            json={"gaps": ["time travel"], "document_id": ""},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1


def test_from_gaps_api_503_ollama_offline(client):
    """POST /flashcards/from-gaps returns 503 when Ollama is unreachable."""
    import litellm

    mock_llm = AsyncMock(side_effect=litellm.ServiceUnavailableError("offline", None, None))
    with patch("app.services.llm.LLMService.generate", mock_llm):
        resp = client.post(
            "/flashcards/from-gaps",
            json={"gaps": ["photosynthesis"], "document_id": ""},
        )
    assert resp.status_code == 503
    assert "ollama serve" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_from_gaps_creates_flashcards():
    """FlashcardService.generate_from_gaps creates one flashcard per parseable gap."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.database import make_engine
    from app.db_init import create_all_tables
    from app.models import FlashcardModel
    from app.services.flashcard import get_flashcard_service

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    gaps = ["concept A", "concept B"]
    llm_responses = [
        '{"front": "What is concept A?", "back": "Concept A is important"}',
        '{"front": "What is concept B?", "back": "Concept B matters"}',
    ]

    call_idx = 0

    async def _mock_generate(prompt, system=None, stream=False):
        nonlocal call_idx
        resp = llm_responses[call_idx % len(llm_responses)]
        call_idx += 1
        return resp

    svc = get_flashcard_service()
    async with factory() as session:
        with patch("app.services.llm.LLMService.generate", side_effect=_mock_generate):
            count, ids = await svc.generate_from_gaps(
                gaps=gaps,
                document_id="doc-test",
                session=session,
            )

    assert count == 2
    assert len(ids) == 2

    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.source == "gap")
        )
        cards = result.scalars().all()

    assert len(cards) == 2
    assert all(c.fsrs_state == "new" for c in cards)
    assert all(c.document_id == "doc-test" for c in cards)


@pytest.mark.asyncio
async def test_generate_from_gaps_skips_malformed_llm():
    """FlashcardService.generate_from_gaps skips gaps with unparseable LLM responses."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.database import make_engine
    from app.db_init import create_all_tables
    from app.models import FlashcardModel
    from app.services.flashcard import get_flashcard_service

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    gaps = ["valid gap", "bad gap"]
    responses = [
        '{"front": "Valid question?", "back": "Valid answer"}',
        "I cannot generate a flashcard for this.",  # malformed — no JSON object
    ]
    call_idx = 0

    async def _mock_generate(prompt, system=None, stream=False):
        nonlocal call_idx
        resp = responses[call_idx % len(responses)]
        call_idx += 1
        return resp

    svc = get_flashcard_service()
    async with factory() as session:
        with patch("app.services.llm.LLMService.generate", side_effect=_mock_generate):
            count, ids = await svc.generate_from_gaps(
                gaps=gaps,
                document_id="",
                session=session,
            )

    assert count == 1
    assert len(ids) == 1

    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.source == "gap")
        )
        cards = result.scalars().all()

    assert len(cards) == 1
    assert cards[0].question == "Valid question?"


@pytest.mark.asyncio
async def test_gap_card_to_flashcards():
    """End-to-end: POST /flashcards/from-gaps inserts FlashcardModel rows with deck='gaps'."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.database import make_engine
    from app.db_init import create_all_tables
    from app.models import FlashcardModel
    from app.services.flashcard import get_flashcard_service

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    gaps = ["Newton's first law", "photosynthesis"]
    responses = [
        '{"front": "What is Newton\'s first law?", "back": "An object at rest stays at rest"}',
        '{"front": "What is photosynthesis?", "back": "Converting light to glucose"}',
    ]
    call_idx = 0

    async def _mock_generate(prompt, system=None, stream=False):
        nonlocal call_idx
        resp = responses[call_idx % len(responses)]
        call_idx += 1
        return resp

    svc = get_flashcard_service()
    async with factory() as session:
        with patch("app.services.llm.LLMService.generate", side_effect=_mock_generate):
            count, ids = await svc.generate_from_gaps(
                gaps=gaps,
                document_id="doc-e2e",
                session=session,
            )

    assert count == 2
    assert len(ids) == 2

    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.deck == "gaps")
        )
        cards = result.scalars().all()

    assert len(cards) == 2
    assert all(c.deck == "gaps" for c in cards)
    assert all(c.source == "gap" for c in cards)
