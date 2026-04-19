"""Integration tests for Feynman router (S144).

AC5: 3-turn session stored correctly in feynman_turns; gap flashcards present after complete.
AC10: POST /feynman/sessions with Ollama unreachable returns 503 with 'ollama serve'.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FeynmanSessionModel, FeynmanTurnModel, FlashcardModel

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
# AC5: 3-turn session + flashcard generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_turn_session_stores_turns_and_generates_flashcards(test_db):
    """AC5: 3 turns (1 opening + 1 learner + 1 tutor) persisted; feynman flashcards created."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())

    # Seed a document
    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Test Book",
            format="pdf",
            content_type="tech_book",
            word_count=1000,
            page_count=50,
            file_path="/tmp/test.pdf",
            stage="complete",
        )
        session.add(doc)
        await session.commit()

    opening_message = "Please explain closures as if teaching a beginner."
    tutor_response = 'Good attempt. You missed reference capture.\ngaps: ["reference capture"]'
    gap_flashcard_json = (
        '{"front": "What is reference capture in closures?",'
        ' "back": "Closures capture variables by reference."}'
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Create session
        with patch("app.services.feynman_service.get_llm_service") as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(return_value=opening_message)
            mock_llm_factory.return_value = mock_llm

            resp = await client.post(
                "/feynman/sessions",
                json={
                    "document_id": doc_id,
                    "concept": "closures",
                },
            )
        assert resp.status_code == 201, resp.text
        session_id = resp.json()["id"]
        assert resp.json()["opening_message"] == opening_message

        # Step 2: Post a learner message and stream response
        # Mock litellm.acompletion for streaming
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices[0].delta.content = tutor_response
            yield chunk
            end_chunk = MagicMock()
            end_chunk.choices[0].delta.content = ""
            yield end_chunk

        with patch("litellm.acompletion", return_value=mock_stream()):
            with patch("app.services.feynman_service.get_llm_service"):
                resp2 = await client.post(
                    f"/feynman/sessions/{session_id}/message",
                    json={"content": "A closure is a function that captures its environment."},
                )
        assert resp2.status_code == 200
        # Parse SSE events
        events = [line[6:] for line in resp2.text.splitlines() if line.startswith("data: ")]
        assert len(events) > 0
        last_event = json.loads(events[-1])
        assert last_event.get("done") is True

        # Step 3: Complete session
        with patch("app.services.flashcard.get_llm_service") as mock_fc_llm:
            mock_fc_llm_svc = AsyncMock()
            mock_fc_llm_svc.generate = AsyncMock(return_value=gap_flashcard_json)
            mock_fc_llm.return_value = mock_fc_llm_svc

            resp3 = await client.post(f"/feynman/sessions/{session_id}/complete")
        assert resp3.status_code == 200
        complete_data = resp3.json()
        assert complete_data["gap_count"] >= 1

    # Verify feynman_turns in DB: opening (index 0) + learner (index 1) + tutor (index 2) = 3
    async with factory() as session:
        turns = (
            (
                await session.execute(
                    select(FeynmanTurnModel)
                    .where(FeynmanTurnModel.session_id == session_id)
                    .order_by(FeynmanTurnModel.turn_index)
                )
            )
            .scalars()
            .all()
        )

    assert len(turns) >= 3, f"Expected >= 3 turns, got {len(turns)}"
    roles = [t.role for t in turns]
    assert "tutor" in roles
    assert "learner" in roles

    # Verify feynman flashcards created
    async with factory() as session:
        cards = (
            (
                await session.execute(
                    select(FlashcardModel).where(
                        FlashcardModel.document_id == doc_id,
                        FlashcardModel.source == "feynman",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(cards) >= 1
    for card in cards:
        assert card.flashcard_type == "concept_explanation"


# ---------------------------------------------------------------------------
# AC10: Offline 503 test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_offline_returns_503(test_db):
    """AC10: POST /feynman/sessions with Ollama unreachable returns 503 with 'ollama serve'."""
    import litellm

    _engine, _factory, _tmp = test_db
    doc_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("app.services.feynman_service.get_llm_service") as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(
                side_effect=litellm.ServiceUnavailableError(
                    message="Ollama unavailable",
                    llm_provider="ollama",
                    model="mistral",
                )
            )
            mock_llm_factory.return_value = mock_llm

            resp = await client.post(
                "/feynman/sessions",
                json={
                    "document_id": doc_id,
                    "concept": "closures",
                },
            )

    assert resp.status_code == 503
    detail = resp.json().get("detail", "")
    assert "ollama serve" in detail


# ---------------------------------------------------------------------------
# AC9: GET /feynman/sessions returns list with gap_count and status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_feynman_sessions(test_db):
    """AC9: GET /feynman/sessions?document_id=... returns sessions with gap_count."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    async with factory() as session:
        feynman_session = FeynmanSessionModel(
            id=session_id,
            document_id=doc_id,
            section_id=None,
            concept="generators",
            status="complete",
        )
        session.add(feynman_session)
        turn = FeynmanTurnModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_index=0,
            role="tutor",
            content='Explain generators.\ngaps: ["yield semantics"]',
            gaps_identified=["yield semantics"],
        )
        session.add(turn)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/feynman/sessions?document_id={doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["concept"] == "generators"
    assert item["status"] == "complete"
    assert item["gap_count"] == 1
