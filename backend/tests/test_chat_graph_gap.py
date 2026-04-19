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
    """Build a mock get_session_factory callable returning `rows` for any execute.

    `rows` can be a flat list (single execute call returns that list via fetchall)
    or a list of lists (sequential execute calls return different results via
    side_effect -- first() for collection lookup, fetchall() for member lookup).
    """
    if rows and isinstance(rows[0], list):
        # Multiple sequential execute results (S197: collection + members)
        results = []
        for row_set in rows:
            mock_result = MagicMock()
            mock_result.first.return_value = row_set[0] if row_set else None
            mock_result.fetchall.return_value = row_set
            results.append(mock_result)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=results)
    else:
        # Single execute result (legacy tests)
        mock_result = MagicMock()
        mock_result.first.return_value = rows[0] if rows else None
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

    # S197: two-step query -- auto-collection lookup then member lookup
    rows = [
        [("coll-1",)],  # collection query: returns one row
        [("note-1",), ("note-2",), ("note-3",)],  # member query: 3 notes
    ]
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
    assert card["auto_collection_id"] == "coll-1"
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
    """No auto-collection for the document returns a helpful card message."""
    state = _make_minimal_state(doc_ids=["doc-abc"], question="gaps in my notes")
    # No auto-collection found (first() returns None)
    rows = [[]]  # empty first result -> first() returns None -> note_ids = []
    with patch("app.database.get_session_factory", _mock_get_session_factory(rows)):
        result = await notes_gap_node(state)
    answer = result["answer"]
    assert answer.startswith("__card__")
    card = json.loads(answer[8:])
    assert "error" in card
    assert "No notes found" in card["error"]
    assert card["gaps"] == []


# ---------------------------------------------------------------------------
# 6. notes_gap_node — Ollama offline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_ollama_offline_returns_error_card():
    state = _make_minimal_state(doc_ids=["doc-abc"], question="compare notes with book")
    # S197: need >= 3 notes to pass the count check and reach detect_gaps
    rows = [
        [("coll-1",)],  # auto-collection found
        [("note-1",), ("note-2",), ("note-3",)],  # 3 members
    ]
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


# ---------------------------------------------------------------------------
# 7. S197: notes_gap_node auto-fetches from auto-collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_auto_fetches_from_auto_collection():
    """Auto-collection note IDs are auto-fetched and passed to detect_gaps."""
    state = _make_minimal_state(doc_ids=["doc-abc"], question="compare my notes with this book")
    mock_report = {
        "gaps": ["Missing concept A"],
        "covered": ["Concept B"],
        "query_used": "auto-collection gap query",
    }
    mock_detector = MagicMock()
    mock_detector.detect_gaps = AsyncMock(return_value=mock_report)

    rows = [
        [("auto-coll-1",)],  # auto-collection found
        [("n1",), ("n2",), ("n3",), ("n4",)],  # 4 members
    ]
    with (
        patch("app.database.get_session_factory", _mock_get_session_factory(rows)),
        patch("app.services.gap_detector.get_gap_detector", return_value=mock_detector),
    ):
        result = await notes_gap_node(state)

    # Verify detect_gaps called with the auto-collection note IDs
    mock_detector.detect_gaps.assert_awaited_once_with(["n1", "n2", "n3", "n4"], "doc-abc")
    card = json.loads(result["answer"][8:])
    assert card["auto_collection_id"] == "auto-coll-1"
    assert card["gaps"] == ["Missing concept A"]


# ---------------------------------------------------------------------------
# 8. S197: no auto-collection returns helpful card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_no_auto_collection_returns_card():
    """When no auto-collection exists for the document, return a card message."""
    state = _make_minimal_state(doc_ids=["doc-xyz"], question="compare my notes")
    # No auto-collection: first() returns None
    rows = [[]]
    with patch("app.database.get_session_factory", _mock_get_session_factory(rows)):
        result = await notes_gap_node(state)
    card = json.loads(result["answer"][8:])
    assert card["type"] == "gap_result"
    assert "No notes found" in card["error"]
    assert "Start taking notes" in card["error"]


# ---------------------------------------------------------------------------
# 9. S197: fewer than 3 notes returns count-based card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_gap_fewer_than_3_notes_returns_card():
    """When auto-collection has fewer than 3 notes, return a count-based card."""
    state = _make_minimal_state(doc_ids=["doc-abc"], question="compare my notes")
    rows = [
        [("coll-1",)],  # auto-collection found
        [("n1",), ("n2",)],  # only 2 members
    ]
    with patch("app.database.get_session_factory", _mock_get_session_factory(rows)):
        result = await notes_gap_node(state)
    card = json.loads(result["answer"][8:])
    assert card["type"] == "gap_result"
    assert "2 note(s)" in card["error"]
    assert "Take a few more" in card["error"]
