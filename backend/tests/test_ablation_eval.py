"""Tests for retrieval ablation eval wiring (S222)."""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import run_eval
from app.services.retriever import HybridRetriever
from app.types import ScoredChunk


def _chunk(source: str = "vector") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=f"{source}-1",
        document_id="doc-1",
        text="answer hint",
        section_heading="",
        page=0,
        score=1.0,
        source="vector" if source == "graph" else source,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_retriever_strategy_vector_skips_keyword_and_graph(monkeypatch):
    retriever = HybridRetriever()
    calls: list[str] = []

    def fake_vector(query, document_ids, k):  # noqa: ANN001
        calls.append(f"vector:{query}")
        return [_chunk("vector")]

    async def fail_keyword(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("keyword path should not run")

    monkeypatch.setattr(retriever, "vector_search", fake_vector)
    monkeypatch.setattr(retriever, "keyword_search", fail_keyword)

    rows = await retriever.retrieve("query", ["doc-1"], 5, strategy="vector")

    assert calls == ["vector:query"]
    assert rows[0].chunk_id == "vector-1"


@pytest.mark.asyncio
async def test_retriever_strategy_fts_skips_vector(monkeypatch):
    retriever = HybridRetriever()

    def fail_vector(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("vector path should not run")

    async def fake_keyword(query, document_ids, k):  # noqa: ANN001
        return [_chunk("keyword")]

    monkeypatch.setattr(retriever, "vector_search", fail_vector)
    monkeypatch.setattr(retriever, "keyword_search", fake_keyword)

    rows = await retriever.retrieve("query", ["doc-1"], 5, strategy="fts")

    assert rows[0].chunk_id == "keyword-1"


@pytest.mark.asyncio
async def test_retriever_strategy_graph_expands_then_vector(monkeypatch):
    import app.services.retriever as retriever_module

    retriever = HybridRetriever()
    calls: list[str] = []

    async def fake_graph_expand(query: str) -> str:
        calls.append(f"graph:{query}")
        return "expanded query"

    def fake_vector(query, document_ids, k):  # noqa: ANN001
        calls.append(f"vector:{query}")
        return [_chunk("graph")]

    monkeypatch.setattr(retriever_module, "_graph_expand", fake_graph_expand)
    monkeypatch.setattr(retriever, "vector_search", fake_vector)

    rows = await retriever.retrieve("query", ["doc-1"], 5, strategy="graph")

    assert calls == ["graph:query", "vector:expanded query"]
    assert rows[0].chunk_id == "graph-1"


def test_run_eval_ablation_produces_four_metric_sets(monkeypatch):
    strategies_seen: list[str] = []
    history_rows: list[tuple[str, dict]] = []
    store_rows: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        run_eval,
        "load_golden",
        lambda dataset: [
            {
                "question": "What is the answer?",
                "ground_truth_answer": "answer",
                "context_hint": "answer hint",
                "source_file": "",
                "source_document_id": "doc-1",
            }
        ],
    )
    monkeypatch.setattr(run_eval, "load_manifest", lambda: {})
    monkeypatch.setattr(
        run_eval,
        "search_chunks",
        lambda *args, **kwargs: strategies_seen.append(kwargs["strategy"]) or ["answer hint"],
    )
    monkeypatch.setattr(
        run_eval,
        "_lib_append_history",
        lambda dataset, model, metrics, passed, eval_kind: history_rows.append(
            (eval_kind, metrics)
        ),
    )
    monkeypatch.setattr(
        run_eval,
        "_lib_store_results",
        lambda backend_url, dataset, model, metrics, eval_kind: store_rows.append(
            (eval_kind, metrics)
        ),
    )
    monkeypatch.setattr(run_eval, "print_ablation_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_eval.py", "--dataset", "book", "--backend-url", "http://test", "--ablation"],
    )

    run_eval.main()

    assert strategies_seen == ["vector", "fts", "graph", "rrf"]
    assert history_rows[0][0] == "ablation"
    assert set(history_rows[0][1]["ablation_metrics"]) == {"vector", "fts", "graph", "rrf"}
    assert store_rows[0][0] == "ablation"
