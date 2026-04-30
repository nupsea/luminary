"""Tests for S212 iteration 5 -- cross-encoder reranking in HybridRetriever.

The reranker is a sentence-transformers ``CrossEncoder`` loaded lazily inside
``_CrossEncoderReranker._load``. We never load the real model in tests --
patch ``_get_reranker`` to return a stub whose ``score`` method returns
deterministic values.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retriever import HybridRetriever, _rerank_candidates
from app.types import ScoredChunk


def _make_chunk(chunk_id: str, text: str, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        text=text,
        section_heading="",
        page=0,
        score=score,
        source="vector",
    )


def test_rerank_candidates_reorders_by_cross_encoder_score():
    """_rerank_candidates replaces RRF score with cross-encoder score and re-sorts."""
    chunks = [
        _make_chunk("c1", "irrelevant text", score=0.9),
        _make_chunk("c2", "the answer is weena", score=0.5),
        _make_chunk("c3", "tangentially related", score=0.7),
    ]

    mock_reranker = MagicMock()
    # Cross-encoder ranks c2 highest -- the chunk with the answer fact even
    # though its RRF score was lowest.
    mock_reranker.score.return_value = [0.1, 0.95, 0.4]

    with patch("app.services.retriever._get_reranker", return_value=mock_reranker):
        result = _rerank_candidates("who is weena?", chunks, k=2)

    assert [c.chunk_id for c in result] == ["c2", "c3"]
    assert result[0].score == pytest.approx(0.95)
    assert result[1].score == pytest.approx(0.4)
    mock_reranker.score.assert_called_once()


def test_rerank_candidates_falls_back_on_reranker_error():
    """Any reranker exception returns the first k of the original RRF order."""
    chunks = [
        _make_chunk("c1", "first", score=0.9),
        _make_chunk("c2", "second", score=0.7),
        _make_chunk("c3", "third", score=0.5),
    ]
    mock_reranker = MagicMock()
    mock_reranker.score.side_effect = RuntimeError("model file missing")

    with patch("app.services.retriever._get_reranker", return_value=mock_reranker):
        result = _rerank_candidates("query", chunks, k=2)

    assert [c.chunk_id for c in result] == ["c1", "c2"]


def test_rerank_candidates_handles_empty_input():
    """Empty candidate list returns empty without invoking the reranker."""
    result = _rerank_candidates("query", [], k=5)
    assert result == []


@pytest.mark.asyncio
async def test_retrieve_with_rerank_invokes_reranker_and_returns_top_k():
    """retrieve(rerank=True) widens the pool, reranks, and returns top-k."""
    retriever = HybridRetriever()

    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.01) for i in range(50)]

    mock_reranker = MagicMock()
    # Reverse the order: last candidate becomes most relevant.
    mock_reranker.score.return_value = [float(i) for i in range(len(pool))]

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        results = await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, rerank=True, graph_expand=False
        )

    # Reranker should have been called once with the full RRF pool (50 chunks).
    mock_reranker.score.assert_called_once()
    args, _kwargs = mock_reranker.score.call_args
    assert args[0] == "q"
    assert len(args[1]) == 50  # full pool fed to cross-encoder

    # Top-5 are the highest-scored after rerank -- here the last 5 of the pool.
    assert len(results) == 5
    assert results[0].chunk_id == "c49"
    assert results[-1].chunk_id == "c45"


@pytest.mark.asyncio
async def test_retrieve_without_rerank_does_not_invoke_reranker():
    """retrieve(rerank=False) never touches the cross-encoder."""
    retriever = HybridRetriever()

    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.01) for i in range(20)]

    mock_reranker = MagicMock()

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve("q", document_ids=["doc-1"], k=5, graph_expand=False)

    mock_reranker.score.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_with_rerank_falls_back_when_reranker_fails():
    """If reranker errors, retrieve still returns RRF top-k unchanged."""
    retriever = HybridRetriever()

    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.01) for i in range(30)]

    mock_reranker = MagicMock()
    mock_reranker.score.side_effect = RuntimeError("model unavailable")

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        results = await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, rerank=True, graph_expand=False
        )

    # Fallback to RRF top-5 -- no exception propagated.
    assert len(results) == 5
