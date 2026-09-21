"""A /search the harness could not complete is a hole in the measurement, never a miss.

`search_chunks` once returned `[]` on any exception, which scored exactly like a
search that found nothing. On a 4-vCPU Windows host S212 read HR@5 0.0000 with
the backend busy and 0.35 idle with 22 of 40 searches timed out, and neither
number was retrieval.
"""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))
sys.path.insert(0, str(REPO_ROOT))

import run_eval
from evals.lib.retrieval_metrics import arm_metrics

HINT = "the machine was a thing of brass and ivory and quartz that shimmered oddly"


def _search_body(text: str) -> dict:
    return {"results": [{"document_id": "doc-1", "matches": [{"text": text, "global_rank": 1}]}]}


def test_a_timed_out_search_raises_instead_of_returning_no_chunks(monkeypatch):
    def timeout(*args, **kwargs):  # noqa: ANN002, ANN003
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(run_eval.httpx, "get", timeout)

    with pytest.raises(run_eval.SearchFailedError, match="ReadTimeout"):
        run_eval.search_chunks("http://test", "q", "doc-1")


def test_a_search_that_found_nothing_is_still_an_empty_list(monkeypatch):
    """The distinction the fix exists for: an empty result is a real miss."""
    request = httpx.Request("GET", "http://test/search")
    monkeypatch.setattr(
        run_eval.httpx,
        "get",
        lambda *a, **k: httpx.Response(200, json={"results": []}, request=request),
    )

    assert run_eval.search_chunks("http://test", "q", "doc-1") == []


def test_one_failed_search_leaves_every_rate_uncomputed():
    hit = {"context_hint": HINT, "contexts": [HINT]}
    failed = {"context_hint": HINT, "contexts": [""], "search_failed": True}

    assert arm_metrics([hit])["hit_rate_5"] == 1.0
    metrics = arm_metrics([hit, failed])

    assert metrics["search_failures"] == 1
    assert metrics["hit_rate_5"] is None
    assert metrics["mrr"] is None
    assert metrics["ndcg_10"] is None


def test_a_run_with_a_failed_search_fails_the_gate_and_records_no_score(monkeypatch, capsys):
    rows = [
        {
            "question": "found",
            "ground_truth_answer": "a",
            "context_hint": HINT,
            "source_file": "",
            "source_document_id": "doc-1",
        },
        {
            "question": "lost",
            "ground_truth_answer": "a",
            "context_hint": HINT,
            "source_file": "",
            "source_document_id": "doc-1",
        },
    ]
    request = httpx.Request("GET", "http://test/search")

    def get(url, params, timeout):  # noqa: ANN001
        if params["q"] == "lost":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, json=_search_body(HINT), request=request)

    history: list[tuple[dict, bool]] = []
    monkeypatch.setattr(run_eval.httpx, "get", get)
    monkeypatch.setattr(run_eval, "resolve_backend_base", lambda url: url)
    monkeypatch.setattr(run_eval, "shipped_rerank", lambda *a, **k: False)
    monkeypatch.setattr(run_eval, "load_golden", lambda dataset: rows)
    monkeypatch.setattr(run_eval, "load_manifest", lambda: {})
    monkeypatch.setattr(run_eval, "output_stats", lambda *a, **k: None)
    monkeypatch.setattr(run_eval, "stats_delta", lambda *a, **k: None)
    monkeypatch.setattr(run_eval, "capture_environment", lambda *a, **k: {})
    monkeypatch.setattr(run_eval, "self_judging", lambda env: None)
    monkeypatch.setattr(
        run_eval,
        "_lib_append_history",
        lambda dataset, model, metrics, passed, **kw: history.append((metrics, passed)),
    )
    monkeypatch.setattr(run_eval, "_lib_store_results", lambda *a, **k: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_eval.py", "--dataset", "book", "--backend-url", "http://test", "--assert-thresholds"],
    )

    with pytest.raises(SystemExit) as exit_info:
        run_eval.main()

    assert exit_info.value.code == 1
    metrics, passed = history[0]
    assert passed is False
    assert metrics["search_failures"] == 1
    assert metrics["hit_rate_5"] is None, "half a dataset must not report a hit rate"
    assert "could not be computed" in capsys.readouterr().err
