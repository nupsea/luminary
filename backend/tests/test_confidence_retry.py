"""S81: Confidence-adaptive retry tests.

Tests for confidence_gate_node, augment_node, and the full retry loop:
  synthesize_node → confidence_gate_node → augment_node → synthesize_node → END
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.runtime.chat_graph import (
    _route_after_confidence_gate,
    augment_node,
    confidence_gate_node,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    base = {
        "question": "Who is Odysseus?",
        "rewritten_question": None,
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "intent": "factual",
        "primary_strategy": "search_node",
        "chunks": [],
        "section_context": None,
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "_llm_prompt": None,
        "_system_prompt": None,
        "retry_attempted": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# confidence_gate_node and routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confidence_gate_node_returns_empty_dict():
    """confidence_gate_node is a no-op node — routing is done by the conditional edge."""
    state = _make_state(confidence="low", retry_attempted=False)
    result = await confidence_gate_node(state)
    assert result == {}


def test_low_confidence_first_attempt_routes_to_augment():
    """_route_after_confidence_gate routes to augment_node when low + not retried."""
    state = _make_state(confidence="low", retry_attempted=False)
    assert _route_after_confidence_gate(state) == "augment_node"


def test_medium_confidence_skips_retry():
    """_route_after_confidence_gate routes to END when confidence is medium."""
    state = _make_state(confidence="medium", retry_attempted=False)
    from langgraph.graph import END  # noqa: PLC0415

    assert _route_after_confidence_gate(state) == END


def test_high_confidence_skips_retry():
    """_route_after_confidence_gate routes to END when confidence is high."""
    state = _make_state(confidence="high", retry_attempted=False)
    from langgraph.graph import END  # noqa: PLC0415

    assert _route_after_confidence_gate(state) == END


def test_no_double_retry():
    """_route_after_confidence_gate routes to END even if confidence='low' on second pass."""
    state = _make_state(confidence="low", retry_attempted=True)
    from langgraph.graph import END  # noqa: PLC0415

    assert _route_after_confidence_gate(state) == END


# ---------------------------------------------------------------------------
# augment_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_augment_node_sets_retry_attempted():
    """augment_node always sets retry_attempted=True in its return dict."""
    state = _make_state(primary_strategy="search_node")

    with patch("app.runtime.chat_nodes.confidence.get_retriever"):
        # For search_node strategy, augment uses Kuzu (no retriever call for search)
        # Mock graph service to raise so we fall through non-fatally
        with patch("app.services.graph.get_graph_service", side_effect=Exception("no graph")):
            result = await augment_node(state)

    assert result.get("retry_attempted") is True


@pytest.mark.asyncio
async def test_augment_appends_chunks():
    """augment_node for relational strategy APPENDS new chunks to existing ones."""
    existing_chunk = {
        "chunk_id": "c1",
        "document_id": "d1",
        "text": "existing chunk",
        "section_heading": "Ch1",
        "page": 1,
        "score": 0.9,
        "source": "vector",
    }
    state = _make_state(
        primary_strategy="graph_node",  # relational → hybrid search k=15
        chunks=[existing_chunk],
    )

    new_chunk = MagicMock()
    new_chunk.chunk_id = "c2"
    new_chunk.document_id = "d1"
    new_chunk.text = "new chunk from augment"
    new_chunk.section_heading = "Ch2"
    new_chunk.page = 2
    new_chunk.score = 0.8
    new_chunk.source = "keyword"

    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(return_value=[new_chunk])

    with patch("app.runtime.chat_nodes.confidence.get_retriever", return_value=mock_retriever):
        result = await augment_node(state)

    combined = result.get("chunks", [])
    assert len(combined) > 1, "augment_node must APPEND chunks, not replace them"
    assert combined[0] == existing_chunk, "Original chunk must be preserved at index 0"
    assert combined[1]["chunk_id"] == "c2", "New chunk must be appended"


@pytest.mark.asyncio
async def test_augment_non_fatal():
    """augment_node catches all exceptions and returns {retry_attempted: True}."""
    state = _make_state(primary_strategy="graph_node")

    patch_target = "app.runtime.chat_nodes.confidence.get_retriever"
    with patch(patch_target, side_effect=Exception("retriever down")):
        result = await augment_node(state)

    assert result.get("retry_attempted") is True
    # Must NOT raise; chunks/section_context changes are optional on error
    assert "chunks" not in result or isinstance(result.get("chunks"), list)


@pytest.mark.asyncio
async def test_graph_knowledge_supplements_factual():
    """augment_node for search_node strategy appends Kuzu graph lines to section_context."""
    state = _make_state(
        primary_strategy="search_node",
        question="Who is Odysseus?",
        section_context="",
    )

    mock_conn = MagicMock()
    # First execute() call (CO_OCCURS): returns 1 result
    co_occurs_result = MagicMock()
    co_occurs_result.has_next.side_effect = [True, False]
    co_occurs_result.get_next.return_value = ["Telemachus", 0.9]

    related_to_result = MagicMock()
    related_to_result.has_next.return_value = False

    mock_conn.execute.side_effect = [co_occurs_result, related_to_result]

    mock_graph_svc = MagicMock()
    mock_graph_svc._conn = mock_conn

    with patch("app.services.graph.get_graph_service", return_value=mock_graph_svc):
        result = await augment_node(state)

    combined_context = result.get("section_context", "")
    assert combined_context, "section_context must be non-empty after graph augment"
    assert "Odysseus" in combined_context or "graph" in combined_context.lower(), (
        f"Expected graph lines in section_context, got: {combined_context[:200]}"
    )
    assert result.get("retry_attempted") is True
