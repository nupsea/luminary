"""Tests for S58 — query rewriting via Kuzu entity lookup.

All tests mock both the Kuzu graph service and the LLM service so no model
downloads or live databases are required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.qa import _maybe_rewrite_query

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_graph_service(entity_names: list[str]) -> MagicMock:
    svc = MagicMock()
    svc.get_entities_for_documents.return_value = entity_names
    return svc


def _make_llm_service(rewritten: str) -> MagicMock:
    svc = MagicMock()
    svc.generate = AsyncMock(return_value=rewritten)
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_rewrite_when_no_vague_refs():
    """Question without vague pronouns: zero LLM calls, zero Kuzu queries."""
    question = "What is osmosis?"
    mock_graph = _make_graph_service(["Alice", "Bob"])
    mock_llm = _make_llm_service("irrelevant")

    with (
        patch("app.services.qa.get_graph_service", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        result = await _maybe_rewrite_query(question, ["doc-1"])

    assert result == question
    mock_graph.get_entities_for_documents.assert_not_called()
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_triggered_for_pronoun():
    """Question with 'they' and document_ids: LLM called with entity list."""
    question = "What did they decide?"
    entities = ["Alice", "Bob", "London"]
    mock_graph = _make_graph_service(entities)
    mock_llm = _make_llm_service("What did Alice and Bob decide?")

    with (
        patch("app.services.qa.get_graph_service", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        result = await _maybe_rewrite_query(question, ["doc-1"])

    assert result == "What did Alice and Bob decide?"
    mock_graph.get_entities_for_documents.assert_called_once_with(["doc-1"])
    mock_llm.generate.assert_called_once()
    # The LLM prompt must include the entity names
    call_kwargs = mock_llm.generate.call_args
    prompt_arg = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("prompt", "")
    assert "Alice" in prompt_arg
    assert "Bob" in prompt_arg


@pytest.mark.asyncio
async def test_skip_rewrite_for_all_scope():
    """document_ids=None (all-docs scope): rewriting skipped entirely."""
    question = "What did they argue about?"
    mock_graph = _make_graph_service(["Alice", "Bob"])
    mock_llm = _make_llm_service("irrelevant")

    with (
        patch("app.services.qa.get_graph_service", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        result = await _maybe_rewrite_query(question, None)

    assert result == question
    mock_graph.get_entities_for_documents.assert_not_called()
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_skip_rewrite_when_kuzu_empty():
    """No entities found in Kuzu: original question returned."""
    question = "What did they decide?"
    mock_graph = _make_graph_service([])  # empty entity list
    mock_llm = _make_llm_service("irrelevant")

    with (
        patch("app.services.qa.get_graph_service", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        result = await _maybe_rewrite_query(question, ["doc-1"])

    assert result == question
    mock_graph.get_entities_for_documents.assert_called_once()
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_returns_original():
    """LLM throws exception: original question returned (non-fatal)."""
    question = "What did they decide?"
    mock_graph = _make_graph_service(["Alice", "Bob"])
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=RuntimeError("connection refused"))

    with (
        patch("app.services.qa.get_graph_service", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        result = await _maybe_rewrite_query(question, ["doc-1"])

    assert result == question
    mock_llm.generate.assert_called_once()
