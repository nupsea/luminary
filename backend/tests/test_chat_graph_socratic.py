"""Tests for S98: socratic intent classification and socratic_node __card__ SSE protocol.

Covers:
  (a) test_socratic_intent_heuristic: classify_intent_heuristic returns ('socratic', 0.95)
  (b) test_socratic_no_false_positive: 'what is the main theme?' does not return 'socratic'
  (c) test_socratic_node_returns_card: mock retriever + litellm; assert __card__ output
  (d) test_socratic_parse_fallback: malformed LLM response yields fallback question, no exception
  (e) test_socratic_ollama_offline: ServiceUnavailableError yields error card, no exception
  (f) test_route_node_socratic: route_node returns 'socratic_node' when intent='socratic'
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.runtime.chat_graph import route_node, socratic_node
from app.services.intent import classify_intent_heuristic
from app.types import ChatState, ScoredChunk  # noqa: F401

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


def _make_chunk(text: str = "Sample passage content.") -> ScoredChunk:
    return ScoredChunk(
        chunk_id="c1",
        document_id="doc1",
        text=text,
        section_heading="Introduction",
        page=1,
        score=0.9,
        source="vector",
        chunk_index=0,
    )


# ---------------------------------------------------------------------------
# (a) Intent heuristic returns socratic for quiz phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "quiz me",
        "quiz me on this",
        "Quiz me on the key concepts",  # exact S95 pill label — must route to socratic
        "test me",
        "test me on this chapter",
        "ask me a question",
        "ask me questions about the book",
        "socratic mode",
        "give me a question",
        "question me",
        "what should i know",
    ],
)
def test_socratic_intent_heuristic(phrase: str):
    intent, confidence = classify_intent_heuristic(phrase)
    assert intent == "socratic", f"Expected 'socratic' for {phrase!r}, got {intent!r}"
    assert confidence == 0.95


# ---------------------------------------------------------------------------
# (b) No false positive: 'what is the main theme?' is NOT socratic
# ---------------------------------------------------------------------------


def test_socratic_no_false_positive():
    intent, _ = classify_intent_heuristic("what is the main theme?")
    assert intent != "socratic"


def test_socratic_no_false_positive_factual():
    intent, _ = classify_intent_heuristic("who is the main character?")
    assert intent != "socratic"


# ---------------------------------------------------------------------------
# (c) socratic_node returns valid __card__ with parsed Q and CONTEXT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_socratic_node_returns_card():
    chunks = [_make_chunk("Achilles was a great hero of ancient Greece.")]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=chunks)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Q: Who is Achilles?\nCONTEXT: Achilles is the hero."

    mock_acompletion = AsyncMock(return_value=mock_response)
    with (
        patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever),
        patch("app.runtime.chat_graph.litellm.acompletion", new=mock_acompletion),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.LITELLM_DEFAULT_MODEL = "ollama/test"
        state = _make_minimal_state(doc_ids=["doc1"])
        result = await socratic_node(state)

    assert "answer" in result
    answer = result["answer"]
    assert answer.startswith("__card__"), f"Expected __card__ prefix, got: {answer!r}"

    card = json.loads(answer[8:])
    assert card["type"] == "quiz_question"
    assert card["question"] == "Who is Achilles?"
    assert card["context_hint"] == "Achilles is the hero."
    assert card["document_id"] == "doc1"
    assert "error" not in card


# ---------------------------------------------------------------------------
# (d) Parse fallback: malformed LLM response yields default question, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_socratic_parse_fallback():
    chunks = [_make_chunk("Some content here.")]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=chunks)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    # Malformed: no Q: or CONTEXT: prefixes
    mock_response.choices[0].message.content = "Here is something unparseable and random."

    mock_acompletion2 = AsyncMock(return_value=mock_response)
    with (
        patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever),
        patch("app.runtime.chat_graph.litellm.acompletion", new=mock_acompletion2),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.LITELLM_DEFAULT_MODEL = "ollama/test"
        state = _make_minimal_state(doc_ids=["doc1"])
        result = await socratic_node(state)

    assert "answer" in result
    card = json.loads(result["answer"][8:])
    assert card["type"] == "quiz_question"
    # Fallback defaults
    assert card["question"] == "What are the main ideas in this material?"
    assert "error" not in card


# ---------------------------------------------------------------------------
# (e) Ollama offline: ServiceUnavailableError -> card with error field, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_socratic_ollama_offline():
    import litellm as _litellm

    chunks = [_make_chunk("Some content.")]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=chunks)

    with (
        patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever),
        patch(
            "app.runtime.chat_graph.litellm.acompletion",
            side_effect=_litellm.ServiceUnavailableError(
                llm_provider="ollama", model="ollama/test", message="Connection refused"
            ),
        ),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.LITELLM_DEFAULT_MODEL = "ollama/test"
        state = _make_minimal_state(doc_ids=["doc1"])
        # Must not raise
        result = await socratic_node(state)

    assert "answer" in result
    card = json.loads(result["answer"][8:])
    assert card["type"] == "quiz_question"
    assert "error" in card
    assert "check settings" in card["error"].lower()


# ---------------------------------------------------------------------------
# (f) route_node returns 'socratic_node' for intent='socratic'
# ---------------------------------------------------------------------------


def test_route_node_socratic():
    state = _make_minimal_state(intent="socratic", scope="all")
    result = route_node(state)
    assert result == "socratic_node"
