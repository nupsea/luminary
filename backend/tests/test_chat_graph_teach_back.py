"""Tests for S99: teach_back intent classification and teach_back_node __card__ SSE protocol.

Covers:
  (a) test_teach_back_intent_heuristic: returns ('teach_back', 0.95) for first-person phrases
  (b) test_teach_back_no_false_positive: imperative 'explain X to me' != teach_back
  (c) test_teach_back_node_returns_card: valid JSON -> __card__ with correct/misconceptions/gaps
  (d) test_teach_back_malformed_json_fallback: non-JSON LLM response -> fallback card, no exception
  (e) test_teach_back_ollama_offline: ServiceUnavailableError -> error card, no exception
  (f) test_route_node_teach_back: route_node returns 'teach_back_node' for intent='teach_back'
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.runtime.chat_graph import route_node, teach_back_node
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
        section_heading="Chapter 1",
        page=1,
        score=0.9,
        source="vector",
        chunk_index=0,
    )


# ---------------------------------------------------------------------------
# (a) Intent heuristic returns teach_back for first-person phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", [
    "let me explain what I understand",
    "my understanding is that the earth revolves around the sun",
    "i think this means the force equals mass times acceleration",
    "i understand this as a recursive process",
    "in my own words, osmosis is the movement of water",
    "i believe that quantum states collapse on observation",
    "if i understand correctly, the mitochondria is the powerhouse",
    "here is my understanding of the water cycle",
])
def test_teach_back_intent_heuristic(phrase: str):
    intent, confidence = classify_intent_heuristic(phrase)
    assert intent == "teach_back", f"Expected 'teach_back' for {phrase!r}, got {intent!r}"
    assert confidence == 0.95


# ---------------------------------------------------------------------------
# (b) No false positive: imperative 'explain X to me' != teach_back
# ---------------------------------------------------------------------------


def test_teach_back_no_false_positive():
    intent, _ = classify_intent_heuristic("explain quantum entanglement to me")
    assert intent != "teach_back"


def test_teach_back_no_false_positive_summary():
    intent, _ = classify_intent_heuristic("what are the main themes of this book?")
    assert intent != "teach_back"


# ---------------------------------------------------------------------------
# (c) teach_back_node returns valid __card__ with parsed JSON fields
# ---------------------------------------------------------------------------

_VALID_EVAL_JSON = json.dumps({
    "correct": ["The earth orbits the sun"],
    "misconceptions": ["The sun is not at the center of the universe"],
    "gaps": ["The concept of gravitational pull was not mentioned"],
    "encouragement": "Great effort on explaining orbital mechanics!",
})


@pytest.mark.asyncio
async def test_teach_back_node_returns_card():
    chunks = [_make_chunk("The earth orbits the sun due to gravity.")]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=chunks)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = _VALID_EVAL_JSON

    mock_acompletion = AsyncMock(return_value=mock_response)
    with (
        patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever),
        patch("app.runtime.chat_graph.litellm.acompletion", new=mock_acompletion),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.LITELLM_DEFAULT_MODEL = "ollama/test"
        state = _make_minimal_state(
            question="my understanding is that the earth goes around the sun",
            doc_ids=["doc1"],
        )
        result = await teach_back_node(state)

    assert "answer" in result
    answer = result["answer"]
    assert answer.startswith("__card__"), f"Expected __card__ prefix, got: {answer!r}"

    card = json.loads(answer[8:])
    assert card["type"] == "teach_back_result"
    assert card["correct"] == ["The earth orbits the sun"]
    assert card["misconceptions"] == ["The sun is not at the center of the universe"]
    assert card["gaps"] == ["The concept of gravitational pull was not mentioned"]
    assert "encouragement" in card
    assert card["document_id"] == "doc1"
    assert "error" not in card


# ---------------------------------------------------------------------------
# (d) Malformed JSON fallback: non-JSON response -> fallback card, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teach_back_malformed_json_fallback():
    chunks = [_make_chunk("Some content.")]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=chunks)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is not valid JSON at all!"

    mock_acompletion = AsyncMock(return_value=mock_response)
    with (
        patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever),
        patch("app.runtime.chat_graph.litellm.acompletion", new=mock_acompletion),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.LITELLM_DEFAULT_MODEL = "ollama/test"
        state = _make_minimal_state(
            question="i think this means something important",
            doc_ids=["doc1"],
        )
        result = await teach_back_node(state)

    assert "answer" in result
    card = json.loads(result["answer"][8:])
    assert card["type"] == "teach_back_result"
    assert "encouragement" in card
    assert "Try rephrasing" in card["encouragement"]
    assert "error" not in card


# ---------------------------------------------------------------------------
# (e) Ollama offline: ServiceUnavailableError -> error card, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teach_back_ollama_offline():
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
        state = _make_minimal_state(
            question="my understanding is that X equals Y",
            doc_ids=["doc1"],
        )
        result = await teach_back_node(state)

    assert "answer" in result
    card = json.loads(result["answer"][8:])
    assert card["type"] == "teach_back_result"
    assert "error" in card
    assert "ollama serve" in card["error"].lower()


# ---------------------------------------------------------------------------
# (f) route_node returns 'teach_back_node' for intent='teach_back'
# ---------------------------------------------------------------------------


def test_route_node_teach_back():
    state = _make_minimal_state(intent="teach_back", scope="all")
    result = route_node(state)
    assert result == "teach_back_node"
