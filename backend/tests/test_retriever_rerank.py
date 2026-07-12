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


def test_rerank_threshold_cuts_low_scores():
    """Candidates below the threshold are dropped even when k has room."""
    chunks = [_make_chunk(f"c{i}", f"text {i}") for i in range(4)]
    mock_reranker = MagicMock()
    mock_reranker.score.return_value = [5.0, -3.0, 2.0, -8.0]

    with patch("app.services.retriever._get_reranker", return_value=mock_reranker):
        result = _rerank_candidates("q", chunks, k=4, threshold=0.0)

    assert [c.chunk_id for c in result] == ["c0", "c2"]


def test_rerank_threshold_keeps_top_candidate_when_all_below():
    """A threshold that cuts everything still returns the best candidate."""
    chunks = [_make_chunk(f"c{i}", f"text {i}") for i in range(3)]
    mock_reranker = MagicMock()
    mock_reranker.score.return_value = [-5.0, -1.0, -9.0]

    with patch("app.services.retriever._get_reranker", return_value=mock_reranker):
        result = _rerank_candidates("q", chunks, k=3, threshold=0.0)

    assert [c.chunk_id for c in result] == ["c1"]


def test_rerank_error_ignores_threshold():
    """Fail-soft path returns RRF top-k without applying the score cut."""
    chunks = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.1) for i in range(3)]
    mock_reranker = MagicMock()
    mock_reranker.score.side_effect = RuntimeError("boom")

    with patch("app.services.retriever._get_reranker", return_value=mock_reranker):
        result = _rerank_candidates("q", chunks, k=2, threshold=100.0)

    assert [c.chunk_id for c in result] == ["c0", "c1"]


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
        # blend=0 isolates the pure cross-encoder ordering (the default blends
        # with RRF); this asserts the CE reordering mechanics deterministically.
        results = await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, rerank=True, rerank_blend=0.0, graph_expand=False
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
async def test_retrieve_rerank_blend_guards_confident_rrf_hit():
    """A high blend weight lets a confident RRF hit survive a CE that would
    otherwise demote it (the fix for pure-CE netting negative HR@5)."""
    retriever = HybridRetriever()
    # c0 is RRF's top hit; the CE ranks it LAST. With blend=0.7 (RRF-heavy) c0
    # must still come out on top instead of being demoted.
    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.01) for i in range(50)]
    mock_reranker = MagicMock()
    mock_reranker.score.return_value = [float(i) for i in range(len(pool))]

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        results = await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, rerank=True, rerank_blend=0.7, graph_expand=False
        )

    assert results[0].chunk_id == "c0"


def test_adaptive_alpha_scales_with_ce_confidence():
    """guard-when-CE-weak: a peaked CE (clear winner) yields a low blend weight
    (trust CE); a flat CE yields the full ceiling (fall back to RRF)."""
    from app.services.retriever import _adaptive_alpha

    # one score far above the rest -> confident -> alpha near 0
    peaked = [10.0] + [0.0] * 20
    assert _adaptive_alpha(peaked, 0.7) < 0.15
    # all scores identical -> no signal -> full ceiling
    flat = [1.0] * 20
    assert _adaptive_alpha(flat, 0.7) == 0.7
    # mildly separated -> intermediate
    mid = [3.0] + [1.0] * 20
    a = _adaptive_alpha(mid, 0.7)
    assert 0.0 <= a <= 0.7


@pytest.mark.asyncio
async def test_retrieve_rerank_depth_controls_pool():
    """rerank_depth overrides the settings default for the cross-encoder pool."""
    retriever = HybridRetriever()
    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.001) for i in range(100)]

    mock_reranker = MagicMock()
    mock_reranker.score.side_effect = lambda q, texts: [0.5] * len(texts)

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, rerank=True, rerank_depth=30, graph_expand=False
        )

    args, _kwargs = mock_reranker.score.call_args
    assert len(args[1]) == 30


@pytest.mark.asyncio
async def test_retrieve_rerank_depth_is_capped():
    """Request-supplied depth cannot exceed the DoS guardrail."""
    retriever = HybridRetriever()
    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.001) for i in range(300)]

    mock_reranker = MagicMock()
    mock_reranker.score.side_effect = lambda q, texts: [0.5] * len(texts)

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, rerank=True, rerank_depth=9999, graph_expand=False
        )

    args, _kwargs = mock_reranker.score.call_args
    assert len(args[1]) == 200


@pytest.mark.asyncio
async def test_retrieve_rerank_threshold_flows_to_results():
    """rerank_threshold cuts low-scoring chunks from retrieve() output."""
    retriever = HybridRetriever()
    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.01) for i in range(20)]

    mock_reranker = MagicMock()
    # Only the first two candidates clear the cut.
    mock_reranker.score.side_effect = lambda q, texts: [
        3.0 if i < 2 else -3.0 for i in range(len(texts))
    ]

    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._get_reranker", return_value=mock_reranker),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        results = await retriever.retrieve(
            "q",
            document_ids=["doc-1"],
            k=5,
            rerank=True,
            rerank_threshold=0.0,
            graph_expand=False,
        )

    assert len(results) == 2
    assert all(c.score >= 0.0 for c in results)


@pytest.mark.asyncio
async def test_retrieve_without_rerank_pool_respects_k():
    """A no-rerank request for k>50 must fetch legs that deep -- the eval
    pool-recall arm reads the raw RRF pool at limit=200 and a silently
    truncated 50-deep pool would understate L1 recall."""
    retriever = HybridRetriever()
    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.001) for i in range(300)]

    with (
        patch.object(retriever, "vector_search", return_value=pool) as mock_vec,
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)) as mock_kw,
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        results = await retriever.retrieve(
            "q", document_ids=["doc-1"], k=200, graph_expand=False
        )

    assert mock_vec.call_args[0][2] == 200
    assert mock_kw.call_args.kwargs["k"] == 200
    assert len(results) == 200


@pytest.mark.asyncio
async def test_retrieve_expand_context_false_skips_expansion():
    """expand_context=False returns the raw ranked list -- no neighbour chunks."""
    retriever = HybridRetriever()
    pool = [_make_chunk(f"c{i}", f"text {i}", score=1.0 - i * 0.01) for i in range(20)]

    mock_expand = AsyncMock(side_effect=lambda r, k: r)
    with (
        patch.object(retriever, "vector_search", return_value=pool),
        patch.object(retriever, "keyword_search", new=AsyncMock(return_value=pool)),
        patch("app.services.retriever._expand_context", new=mock_expand),
    ):
        results = await retriever.retrieve(
            "q", document_ids=["doc-1"], k=5, graph_expand=False, expand_context=False
        )

    mock_expand.assert_not_called()
    assert len(results) == 5


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
