"""Tests for S212 iteration 4 -- HyDE-style query expansion in HybridRetriever.

The retriever delegates to the LLM service for hypothetical-answer generation.
The LLM is imported lazily inside ``_hyde_expand`` (circular-import guard), so
patch target is ``app.services.llm.get_llm_service``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retriever import HybridRetriever, _hyde_expand
from app.types import ScoredChunk


def _make_chunk(chunk_id: str, document_id: str = "doc-1") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=f"text for {chunk_id}",
        section_heading="",
        page=0,
        score=1.0,
        source="vector",
    )


@pytest.mark.asyncio
async def test_hyde_expand_concatenates_hypothetical_to_query():
    """When LLM returns a hypothetical, _hyde_expand returns 'query + hypothetical'."""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value="The girl's name was Weena.")

    with patch("app.services.llm.get_llm_service", return_value=mock_llm):
        result = await _hyde_expand("Who was the Eloi girl?")

    assert result == "Who was the Eloi girl? The girl's name was Weena."
    mock_llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_hyde_expand_falls_back_on_llm_error():
    """LLM exception (Ollama down, timeout) returns original query unchanged."""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=RuntimeError("ollama unreachable"))

    with patch("app.services.llm.get_llm_service", return_value=mock_llm):
        result = await _hyde_expand("Who was Weena?")

    assert result == "Who was Weena?"


@pytest.mark.asyncio
async def test_hyde_expand_falls_back_on_empty_response():
    """Empty/whitespace LLM response returns original query unchanged."""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value="   ")

    with patch("app.services.llm.get_llm_service", return_value=mock_llm):
        result = await _hyde_expand("Who was Weena?")

    assert result == "Who was Weena?"


@pytest.mark.asyncio
async def test_retrieve_with_hyde_passes_augmented_query_to_searches():
    """retrieve(hyde=True) augments the query before vector and BM25 search."""
    retriever = HybridRetriever()

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value="Hypothetical answer.")

    with (
        patch("app.services.llm.get_llm_service", return_value=mock_llm),
        patch.object(
            retriever, "vector_search", return_value=[_make_chunk("c1")]
        ) as vec_mock,
        patch.object(
            retriever, "keyword_search", new=AsyncMock(return_value=[_make_chunk("c2")])
        ) as kw_mock,
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve("What happened?", document_ids=["doc-1"], k=5, hyde=True)

    assert vec_mock.call_count == 1
    assert kw_mock.await_count == 1
    vec_query = vec_mock.call_args[0][0]
    kw_query = kw_mock.call_args[0][0]
    assert vec_query == "What happened? Hypothetical answer."
    assert kw_query == "What happened? Hypothetical answer."


@pytest.mark.asyncio
async def test_retrieve_without_hyde_uses_original_query():
    """retrieve(hyde=False) sends the unmodified query and never calls the LLM."""
    retriever = HybridRetriever()

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value="should not be called")

    with (
        patch("app.services.llm.get_llm_service", return_value=mock_llm),
        patch.object(
            retriever, "vector_search", return_value=[_make_chunk("c1")]
        ) as vec_mock,
        patch.object(
            retriever, "keyword_search", new=AsyncMock(return_value=[_make_chunk("c2")])
        ),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve("What happened?", document_ids=["doc-1"], k=5)

    mock_llm.generate.assert_not_called()
    assert vec_mock.call_args[0][0] == "What happened?"


@pytest.mark.asyncio
async def test_retrieve_with_hyde_falls_back_when_llm_fails():
    """If LLM errors, retrieve still returns results using the unmodified query."""
    retriever = HybridRetriever()

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=TimeoutError("model timed out"))

    with (
        patch("app.services.llm.get_llm_service", return_value=mock_llm),
        patch.object(
            retriever, "vector_search", return_value=[_make_chunk("c1")]
        ) as vec_mock,
        patch.object(
            retriever, "keyword_search", new=AsyncMock(return_value=[_make_chunk("c2")])
        ),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        results = await retriever.retrieve(
            "What happened?", document_ids=["doc-1"], k=5, hyde=True
        )

    assert vec_mock.call_args[0][0] == "What happened?"
    assert results  # graceful degradation -- retrieval still succeeded
