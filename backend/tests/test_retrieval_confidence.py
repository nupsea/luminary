"""The confidence gate reads the raw reranker logit, never the normalised score (I-73)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from app.runtime.chat_graph import _route_after_confidence_gate, search_node, synthesize_node
from app.runtime.chat_nodes.synthesize import RELEVANT_RERANK_LOGIT, _retrieval_confidence
from app.services.retriever import _rerank_candidates
from app.types import ScoredChunk
from tests.factories import make_document


def _state(**overrides) -> dict:
    base = {
        "question": "What year did the Berlin Wall fall?",
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "intent": "factual",
        "rewritten_question": None,
        "chunks": [],
        "section_context": None,
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "_llm_prompt": None,
        "_system_prompt": None,
        "source_citations": [],
        "transparency": None,
        "transparency_augmented": False,
        "retry_attempted": False,
    }
    base.update(overrides)
    return base


def _candidates(doc_id: str, n: int) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            chunk_id=str(uuid.uuid4()),
            document_id=doc_id,
            text=f"Passage {i} about vector search and BM25.",
            section_heading="Hybrid search",
            page=1,
            score=1.0 / (60 + i + 1),
            source="both",
            chunk_index=i,
        )
        for i in range(n)
    ]


def _chunk(rerank_score: float | None, source: str = "both") -> dict:
    return {
        "chunk_id": str(uuid.uuid4()),
        "document_id": "d",
        "text": "t",
        "score": 1.0,
        "rerank_score": rerank_score,
        "source": source,
    }


@pytest.mark.asyncio
async def test_offtopic_question_reads_low_although_its_normalised_top_score_is_one(test_db):
    """The defect: minmax put every non-empty result's top score at 1.0, so the gate
    read "high" for a question the library cannot answer and the retry never ran.
    Real rerank -> search_node -> synthesize_node, so a dropped field fails here."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(make_document(id=doc_id, title="Retrieval tutorial", format="md"))
        await session.commit()

    reranker = MagicMock()
    # Off-library questions measured library-wide on the dev library.
    reranker.score.return_value = [-6.3, -7.6, -10.2]
    with patch("app.services.retriever._get_reranker", return_value=reranker):
        reranked = _rerank_candidates(
            "What year did the Berlin Wall fall?", _candidates(doc_id, 3), k=3
        )
    assert reranked[0].score == 1.0
    assert reranked[0].rerank_score == -6.3

    retriever = MagicMock()
    retriever.retrieve_with_images = AsyncMock(return_value=(reranked, []))
    with patch("app.runtime.chat_nodes.search.get_retriever", return_value=retriever):
        searched = await search_node(_state())
    assert [c["rerank_score"] for c in searched["chunks"]][0] == -6.3

    synthesized = await synthesize_node(_state(chunks=searched["chunks"]))
    assert synthesized["confidence"] == "low"
    assert _route_after_confidence_gate(_state(confidence="low")) == "augment_node"


@pytest.mark.parametrize(
    "best_logit, expected",
    [
        pytest.param(-0.41, "low", id="bass_guitar_offlibrary_library_wide"),
        pytest.param(0.5, "high", id="lowest_answerable_with_the_answer_in_its_best_passage"),
    ],
)
def test_threshold_sits_between_its_bracketing_cases(best_logit, expected):
    # A context-expansion neighbour carries no logit and must not count.
    chunks = [_chunk(best_logit), _chunk(best_logit - 3.0), _chunk(None, "context_expansion")]
    assert _retrieval_confidence(chunks) == expected
    assert RELEVANT_RERANK_LOGIT == 0.0


def test_no_reranker_score_reads_unknown_and_skips_the_retry():
    """Rerank off, or the reranker not installed: say so, never claim "high"."""
    reranker = MagicMock()
    reranker.score.side_effect = RuntimeError("model not loaded")
    with patch("app.services.retriever._get_reranker", return_value=reranker):
        fallback = _rerank_candidates("q", _candidates("d", 3), k=3)
    chunks = [{"score": c.score, "rerank_score": c.rerank_score} for c in fallback]

    assert _retrieval_confidence(chunks) == "unknown"
    assert _route_after_confidence_gate(_state(confidence="unknown")) == END


def test_nothing_retrieved_reads_low():
    assert _retrieval_confidence([]) == "low"
