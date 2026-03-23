"""Tests for S96: notes_gap intent classification and notes_gap_node __card__ SSE protocol.

Covers:
  1. classify_intent_heuristic returns ('notes_gap', 0.95) for all _NOTES_GAP_KWS phrases
  2. route_node dispatches to 'notes_gap_node' when intent='notes_gap'
  3. notes_gap_node returns a valid __card__ on successful gap detection
  4. notes_gap_node returns error card when doc_ids is empty (no single document)
  5. notes_gap_node returns error card when no notes exist for the document
  6. notes_gap_node returns Ollama-specific error card on ServiceUnavailableError
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from app.runtime.chat_graph import notes_gap_node, route_node
from app.services.intent import _NOTES_GAP_KWS, classify_intent_heuristic
from app.types import ChatState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_state(**overrides) -> ChatState:
    base: dict = {
        "question": "test",
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "intent": None,
        "rewritten_question": None,
        "chunks": [],
        "section_context": None,
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "_llm_prompt": None,
        "_system_prompt": None,
        "retry_attempted": False,
        "primary_strategy": None,
        "conversation_history": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _mock_get_session_factory(rows: list):
    """Build a mock get_session_factory callable returning `rows` for any execute."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_session_maker = MagicMock()
    mock_session_maker.return_value = mock_session

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session_maker
    return mock_factory


# ---------------------------------------------------------------------------
# 1. Intent heuristic — parametrised over all _NOTES_GAP_KWS phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", sorted(_NOTES_GAP_KWS))
def test_notes_gap_intent_heuristic(phrase: str):
    """Every keyword in _NOTES_GAP_KWS must classify as notes_gap with confidence 0.95."""
    intent, confidence = classify_intent_heuristic(phrase)
    assert intent == "notes_gap", f"phrase {phrase!r} -> intent={intent!r}, expected 'notes_gap'"
    assert confidence == 0.95


# ---------------------------------------------------------------------------
# 2. route_node dispatch
# ---------------------------------------------------------------------------


def test_route_node_dispatches_notes_gap():
    state = _make_minimal_state(intent="notes_gap", scope="single", doc_ids=["doc-1"])
    assert route_node(state) == "notes_gap_node"


def test_route_node_notes_gap_not_dispatched_for_other_intents():
    for intent in ("summary", "factual", "relational", "comparative", "exploratory", "notes"):
        state = _make_minimal_state(intent=intent, scope="single")
        assert route_node(state) != "notes_gap_node", (
            f"intent={intent!r} should not route to notes_gap_node"
        )


# ---------------------------------------------------------------------------
# 3. notes_gap_node — successful gap detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_returns_gap_result_card():
    state = _make_minimal_state(doc_ids=["doc-abc"], question="find gaps in my notes")
    mock_report = {
        "gaps": ["Chapter 3 themes not covered"],
        "covered": ["Time travel concept"],
        "query_used": "notes vs doc-abc",
    }
    mock_detector = MagicMock()
    mock_detector.detect_gaps = AsyncMock(return_value=mock_report)

    rows = [("note-1",), ("note-2",)]
    with (
        patch("app.database.get_session_factory", _mock_get_session_factory(rows)),
        patch("app.services.gap_detector.get_gap_detector", return_value=mock_detector),
    ):
        result = await notes_gap_node(state)

    answer = result["answer"]
    assert answer.startswith("__card__"), "answer must carry __card__ sentinel prefix"
    card = json.loads(answer[8:])
    assert card["type"] == "gap_result"
    assert card["gaps"] == ["Chapter 3 themes not covered"]
    assert card["covered"] == ["Time travel concept"]
    assert "error" not in card


# ---------------------------------------------------------------------------
# 4. notes_gap_node — no document selected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_no_document_returns_error_card():
    """Empty doc_ids (scope=all) returns an error card without DB access."""
    state = _make_minimal_state(doc_ids=[], question="find gaps in my notes")
    result = await notes_gap_node(state)
    answer = result["answer"]
    assert answer.startswith("__card__")
    card = json.loads(answer[8:])
    assert card["type"] == "gap_result"
    assert "error" in card
    assert card["gaps"] == []
    assert card["covered"] == []


# ---------------------------------------------------------------------------
# 5. notes_gap_node — no notes linked to document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_no_notes_returns_error_card():
    state = _make_minimal_state(doc_ids=["doc-abc"], question="gaps in my notes")
    with patch("app.database.get_session_factory", _mock_get_session_factory([])):
        result = await notes_gap_node(state)
    answer = result["answer"]
    assert answer.startswith("__card__")
    card = json.loads(answer[8:])
    assert "error" in card
    assert card["gaps"] == []


# ---------------------------------------------------------------------------
# 6. notes_gap_node — Ollama offline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_ollama_offline_returns_error_card():
    state = _make_minimal_state(doc_ids=["doc-abc"], question="compare notes with book")
    rows = [("note-1",)]
    mock_detector = MagicMock()
    mock_detector.detect_gaps = AsyncMock(
        side_effect=litellm.ServiceUnavailableError(
            message="Ollama offline", llm_provider="ollama", model="ollama/mistral"
        )
    )
    with (
        patch("app.database.get_session_factory", _mock_get_session_factory(rows)),
        patch("app.services.gap_detector.get_gap_detector", return_value=mock_detector),
    ):
        result = await notes_gap_node(state)
    answer = result["answer"]
    assert answer.startswith("__card__")
    card = json.loads(answer[8:])
    assert "error" in card
    error_lower = card["error"].lower()
    assert "ollama" in error_lower or "running" in error_lower
    assert card["gaps"] == []
