"""Eval-harness wiring: goldens, metrics, history rows and CLI flags, without a backend.

These ran as smoke scripts S88 and S213-S226, which never called the server; a check
that needs no running app belongs in the suite that gates every push.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVALS = REPO_ROOT / "evals"
for _path in (REPO_ROOT, EVALS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evals.lib import RetrievalEval, RetrievalGoldenEntry  # noqa: E402
from evals.lib.citation_metrics import (  # noqa: E402
    compute_citation_support_rate,
    pair_answer_with_citations,
)
from evals.lib.flashcard_metrics import (  # noqa: E402
    compute_atomicity,
    compute_clarity_avg,
    compute_factuality,
)
from evals.lib.intent_metrics import (  # noqa: E402
    compute_per_route_precision_recall,
    compute_routing_accuracy,
)
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.schemas import (  # noqa: E402
    FlashcardGoldenEntry,
    IntentGoldenEntry,
    SummaryGoldenEntry,
)
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.summary_metrics import (  # noqa: E402
    compute_conciseness_pct,
    compute_no_hallucination,
    compute_theme_coverage,
)

# One dataset per book; a file mixing sources means a generator wrote questions
# about text it was not given.
BOOK_SOURCES = {
    "book": "DATA/books/time_machine.txt",
    "book_time_machine": "DATA/books/time_machine.txt",
    "book_alice": "DATA/books/alice_in_wonderland.txt",
    "book_frankenstein": "DATA/books/frankenstein.txt",
    "odyssey": "DATA/books/the_odyssey.txt",
}
# A collapse detector, not a size target: every book dataset holds 40 today.
BOOK_MINIMUM = 20


def _history_row(tmp_path: Path, *args, **kwargs) -> dict:
    target = tmp_path / "scores.jsonl"
    append_history(*args, path=target, **kwargs)
    return json.loads(target.read_text().strip().splitlines()[-1])


def _help(script: str) -> str:
    out = subprocess.run(
        [sys.executable, script, "--help"], cwd=EVALS, capture_output=True, text=True, check=True
    )
    return out.stdout


@pytest.mark.parametrize(
    ("script", "flags"),
    [
        (
            "run_eval.py",
            [
                "--ablation",
                "--dataset-id",
                "--judge-model",
                "--max-questions",
                "--check-citations",
                "Answer-",
                "Relevance >= 0.50",
            ],
        ),
        ("run_summary_eval.py", ["--mode", "--skip-judge"]),
        ("run_intent_eval.py", ["--assert-thresholds"]),
        ("run_flashcard_eval.py", ["--judge-model"]),
    ],
)
def test_eval_cli_exposes_its_flags(script, flags):
    text = _help(script)
    missing = [f for f in flags if f not in text]
    assert not missing, f"{script} --help lacks {missing}"


def test_generation_judge_dependencies_stay_pinned():
    pyproject = (EVALS / "pyproject.toml").read_text()
    assert "ragas==0.4.3" in pyproject
    assert "datasets==4.5.0" in pyproject


@pytest.mark.parametrize(("name", "source"), sorted(BOOK_SOURCES.items()))
def test_book_golden_is_whole_and_single_sourced(name, source):
    path = EVALS / "golden" / f"{name}.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) >= BOOK_MINIMUM, f"{name}.jsonl has {len(rows)} questions"
    assert {r.get("source_file") for r in rows} == {source}
    assert all(r.get("question") for r in rows)


def test_book_goldens_are_registered_with_the_harness():
    tree = ast.parse((EVALS / "run_eval.py").read_text())
    valid = next(
        [e.value for e in node.value.elts]
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "VALID_DATASETS" for t in node.targets)
    )
    assert not sorted(set(BOOK_SOURCES) - set(valid))


def test_retrieval_package_and_legacy_run_eval_names_agree(tmp_path):
    from run_eval import GoldenEntry, compute_hit_rate_5, compute_mrr

    assert GoldenEntry is RetrievalGoldenEntry
    e = RetrievalGoldenEntry(question="q", ground_truth_answer="a", context_hint="hint")
    assert e.context_hint == ["hint"]
    samples = [{"context_hint": ["x"], "contexts": ["x is here"], "ground_truths": ["g"]}]
    assert compute_hit_rate_5(samples) == 1.0
    assert compute_mrr(samples) == 1.0
    metrics = RetrievalEval().run(samples)
    assert metrics["hit_rate_5"] == 1.0 and metrics["mrr"] == 1.0
    RetrievalEval().assert_thresholds(metrics, {"hit_rate_5": 0.5, "mrr": 0.5})
    row = _history_row(tmp_path, "ds", "no-llm", {"hit_rate_5": 0.6, "mrr": 0.4}, True)
    assert row["eval_kind"] == "retrieval"


def test_golden_audit_passes():
    result = subprocess.run(
        [sys.executable, "-m", "evals.lib.audit"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout


def test_multi_hint_goldens_load_as_lists():
    from pydantic import ValidationError
    from run_eval import GoldenEntry, compute_hit_rate_5, compute_mrr

    assert GoldenEntry(question="q", ground_truth_answer="a", context_hint=["a", "b"]).context_hint
    with pytest.raises(ValidationError):
        GoldenEntry(question="q", ground_truth_answer="a", context_hint=[])
    samples = [
        {
            "question": "q",
            "context_hint": ["needle-A", "needle-B"],
            "contexts": ["chunk1 has needle-B in it"],
            "ground_truths": ["GT"],
        }
    ]
    assert compute_hit_rate_5(samples) == 1.0
    assert compute_mrr(samples) == 1.0
    for ds in ("book_time_machine", "odyssey", "book_alice"):
        rows = load_golden(ds)
        assert rows, f"{ds}: golden is empty"
        assert all(isinstance(r["context_hint"], list) for r in rows)


_GENERATION_KEYS = ("faithfulness", "answer_relevance", "context_precision", "context_recall")


def _install_fake_ragas(monkeypatch, evaluate) -> None:
    def module(name: str, **attrs) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    module("ragas", evaluate=evaluate, __path__=[])
    module("ragas.llms", LangchainLLMWrapper=lambda llm, *a, **k: llm)
    module(
        "ragas.metrics",
        **{
            n: types.SimpleNamespace(llm=None)
            for n in ("answer_relevancy", "context_precision", "context_recall", "faithfulness")
        },
    )
    module(
        "datasets",
        Dataset=type("Dataset", (), {"from_list": classmethod(lambda cls, rows: rows)}),
    )
    module("langchain_community")
    module("langchain_community.chat_models", ChatOllama=lambda *a, **k: object())
    module("langchain_ollama", ChatOllama=lambda *a, **k: object())
    module("langchain_openai", ChatOpenAI=lambda *a, **k: object())
    module("langchain_huggingface", HuggingFaceEmbeddings=lambda *a, **k: object())
    module("ragas.embeddings", LangchainEmbeddingsWrapper=lambda emb, *a, **k: emb)
    module("ragas.run_config", RunConfig=lambda *a, **k: object())


def test_generation_eval_reads_ragas_scores_and_skips_when_the_judge_is_down(monkeypatch):
    import pandas as pd
    from evals.lib.runners import GenerationEval
    from run_eval import THRESHOLDS

    class FakeResult:
        def __init__(self, df):
            self._df = df

        def to_pandas(self):
            return self._df

    scores = {
        "faithfulness": 0.91,
        "answer_relevancy": 0.82,
        "context_precision": 0.73,
        "context_recall": 0.64,
    }
    samples = [
        {"question": "q", "answer": "a", "contexts": ["ctx"], "ground_truths": ["a"]},
    ]
    _install_fake_ragas(monkeypatch, lambda **kw: FakeResult(pd.DataFrame([scores])))
    metrics = GenerationEval().run(samples, judge_model="ollama/test-model")
    assert {k: metrics[k] for k in _GENERATION_KEYS} == {
        "faithfulness": 0.91,
        "answer_relevance": 0.82,
        "context_precision": 0.73,
        "context_recall": 0.64,
    }
    assert THRESHOLDS["faithfulness"] == 0.30
    assert THRESHOLDS["answer_relevance"] == 0.50

    def down(**kw):
        raise ConnectionRefusedError("ollama down")

    _install_fake_ragas(monkeypatch, down)
    metrics = GenerationEval().run(samples, judge_model="ollama/test-model")
    assert {k: metrics[k] for k in _GENERATION_KEYS} == dict.fromkeys(_GENERATION_KEYS)


def test_citation_support_rate_and_history(tmp_path):
    from run_eval import THRESHOLDS

    answer = "Alice opened the small door with a key. She drank from the bottle."
    pairs = pair_answer_with_citations(
        answer,
        [
            {"text": "a golden key lay on the table"},
            {"excerpt": "she drank it off and found it very nice"},
            {"text": ""},
            "not a citation object",
        ],
    )
    assert pairs == [
        (answer, "a golden key lay on the table"),
        (answer, "she drank it off and found it very nice"),
    ]
    verdicts = iter(["yes", "yes", "partial", "no"])
    rate = compute_citation_support_rate(
        [("c1", "x"), ("c2", "x"), ("c3", "x"), ("c4", "x")],
        judge=lambda claim, chunk: next(verdicts),
    )
    assert rate == 0.625
    assert THRESHOLDS["citation_support_rate"] == 0.45
    row = _history_row(
        tmp_path,
        "book_alice",
        "ollama/test",
        {"citation_support_rate": rate},
        False,
        eval_kind="citation",
    )
    assert row["eval_kind"] == "citation"
    assert row["citation_support_rate"] == 0.625


def test_summary_goldens_metrics_and_history(tmp_path):
    rows = load_golden("summaries", SummaryGoldenEntry)
    assert len(rows) >= 9
    assert {r["mode"] for r in rows} >= {"one_sentence", "executive", "detailed"}
    summary = "Alice follows a rabbit into Wonderland and changes size."
    assert compute_theme_coverage(summary, ["alice", "rabbit", "queen", "size|change"]) == 0.75
    assert compute_no_hallucination(0, 5) == 1.0
    assert compute_conciseness_pct("abcd", 8) == 0.5
    scores = {"theme_coverage": 0.75, "no_hallucination": 1.0, "conciseness_pct": 0.5}
    row = _history_row(tmp_path, "summaries", "judge", scores, True, eval_kind="summary")
    assert row["eval_kind"] == "summary"
    assert {k: row[k] for k in scores} == scores


def test_flashcard_goldens_metrics_and_history(tmp_path):
    assert len(load_golden("flashcards", FlashcardGoldenEntry)) >= 6
    assert compute_factuality(["yes", "yes", "partial", "no"]) == 0.625
    assert compute_atomicity([True, False, True]) == 2 / 3
    assert compute_clarity_avg([5, 4, 3]) == 4.0
    scores = {"factuality": 0.625, "atomicity": 0.8, "clarity_avg": 4.0}
    row = _history_row(tmp_path, "flashcards", "judge", scores, True, eval_kind="flashcard")
    assert row["eval_kind"] == "flashcard"
    assert {k: row[k] for k in scores} == scores


def test_intent_goldens_metrics_and_history(tmp_path):
    rows = load_golden("intents", IntentGoldenEntry)
    assert len(rows) >= 50
    assert {"summary", "graph", "comparative", "search"} <= {r["expected_route"] for r in rows}
    samples = [
        {"expected_route": "summary", "predicted_route": "summary"},
        {"expected_route": "search", "predicted_route": "search"},
        {"expected_route": "graph", "predicted_route": "search"},
    ]
    assert compute_routing_accuracy(samples) == 2 / 3
    assert "summary" in compute_per_route_precision_recall(samples)
    row = _history_row(
        tmp_path, "intents", "classifier", {"routing_accuracy": 1.0}, True, eval_kind="intent"
    )
    assert row["eval_kind"] == "intent"
    assert row["routing_accuracy"] == 1.0
