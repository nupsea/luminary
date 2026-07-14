"""Guards the generation-eval integrity fix: a judge scores answers generated
live by /qa — never the golden ground truth (which would self-grade the
dataset) — and retrieval metrics stay on search-only contexts."""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import run_eval

_GOLDEN = [
    {
        "question": "Q1",
        "ground_truth_answer": "GOLD ANSWER ONE",
        "context_hint": "hint one",
        "source_file": "",
        "source_document_id": "doc-1",
    },
    {
        "question": "Q2",
        "ground_truth_answer": "GOLD ANSWER TWO",
        "context_hint": "hint two",
        "source_file": "",
        "source_document_id": "doc-1",
    },
]


class _FakeNliFaithfulness:
    """Deterministic stand-in for the HHEM model so tests never download it.

    Captures the samples it scored so a test can assert the NLI path also sees
    generated answers (not golden ground truth).
    """

    scored_batches: list[list[dict]] = []

    def run(self, samples, **kwargs):
        answered = [s for s in samples if s.get("answer", "").strip()]
        type(self).scored_batches.append(answered)
        if not answered:
            return {"faithfulness": None, "faithfulness_model": None}
        return {"faithfulness": 0.95, "faithfulness_model": "fake/hhem"}


def _wire_common(monkeypatch, history):
    _FakeNliFaithfulness.scored_batches = []
    monkeypatch.setattr(run_eval, "NliFaithfulnessEval", _FakeNliFaithfulness)
    monkeypatch.setattr(run_eval, "load_golden", lambda dataset: [dict(r) for r in _GOLDEN])
    monkeypatch.setattr(run_eval, "load_manifest", lambda: {})
    monkeypatch.setattr(
        run_eval, "search_chunks", lambda *args, **kwargs: ["chunk with hint one inside"]
    )
    monkeypatch.setattr(
        run_eval,
        "_lib_append_history",
        lambda dataset, model, metrics, passed, eval_kind: history.append(
            (eval_kind, model, metrics, passed)
        ),
    )
    # print_table stays real: it must format mixed metric types (floats,
    # strings like answer_model, ints) without crashing.
    monkeypatch.setattr(run_eval, "_lib_store_results", lambda *args, **kwargs: None)


def test_judge_scores_generated_answers_not_golden(monkeypatch):
    history: list[tuple] = []
    judged: list[list[dict]] = []
    qa_calls: list[str] = []

    _wire_common(monkeypatch, history)
    monkeypatch.setattr(
        run_eval,
        "post_qa",
        lambda url, question, model, doc_id: qa_calls.append(question)
        or {"answer": f"GENERATED::{question}", "citations": [{"text": "cited chunk"}]},
    )

    class _FakeGenerationEval:
        def run(self, samples, judge_model):
            judged.append(samples)
            return {
                "faithfulness": 0.9,
                "answer_relevance": 0.8,
                "context_precision": None,
                "context_recall": None,
                "judge_failed_calls": 1,
                "judge_total_calls": 4,
            }

    monkeypatch.setattr(run_eval, "GenerationEval", _FakeGenerationEval)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_eval.py",
            "--dataset", "book",
            "--backend-url", "http://test",
            "--judge-model", "ollama/fake-judge",
        ],
    )

    run_eval.main()

    assert sorted(qa_calls) == ["Q1", "Q2"]
    assert judged, "judge was never invoked"
    answers = {s["answer"] for s in judged[0]}
    assert answers == {"GENERATED::Q1", "GENERATED::Q2"}
    assert not any("GOLD" in a for a in answers)
    # /qa citations feed the judged contexts but must not leak into HR@5/MRR.
    assert "cited chunk" in judged[0][0]["contexts"]

    eval_kind, model, metrics, _ = history[0]
    assert eval_kind == "generation"
    assert model == "ollama/fake-judge"
    assert metrics["answer_model"] == "app-default"
    assert metrics["qa_failed_calls"] == 0
    assert metrics["judge_failed_calls"] == 1
    # Faithfulness now comes from the deterministic NLI scorer, not the judge.
    assert metrics["faithfulness"] == 0.95
    assert metrics["faithfulness_model"] == "fake/hhem"
    # NLI must score the live-generated answers, never the golden ground truth.
    nli_answers = {s["answer"] for s in _FakeNliFaithfulness.scored_batches[-1]}
    assert nli_answers == {"GENERATED::Q1", "GENERATED::Q2"}
    # hint one matches the search chunk, hint two does not: HR@5 = 1/2 either
    # way because retrieval metrics ignore the cited chunk.
    assert metrics["hit_rate_5"] == 0.5


def test_no_judge_by_default_and_no_qa(monkeypatch):
    history: list[tuple] = []
    _wire_common(monkeypatch, history)

    def _fail_qa(*args, **kwargs):
        raise AssertionError("/qa must not be called without a judge or --model")

    monkeypatch.setattr(run_eval, "post_qa", _fail_qa)

    class _FailGenerationEval:
        def run(self, samples, judge_model):
            raise AssertionError("judge must not run by default")

    monkeypatch.setattr(run_eval, "GenerationEval", _FailGenerationEval)
    monkeypatch.setattr(
        sys, "argv", ["run_eval.py", "--dataset", "book", "--backend-url", "http://test"]
    )

    run_eval.main()

    eval_kind, model, metrics, _ = history[0]
    assert eval_kind == "retrieval"
    assert model == "no-llm"
    assert metrics["faithfulness"] is None
    assert "answer_model" not in metrics


def test_judge_skipped_when_qa_returns_nothing(monkeypatch):
    history: list[tuple] = []
    _wire_common(monkeypatch, history)
    monkeypatch.setattr(run_eval, "post_qa", lambda *args, **kwargs: {})

    class _FailGenerationEval:
        def run(self, samples, judge_model):
            raise AssertionError("judge must not run when /qa produced no answers")

    monkeypatch.setattr(run_eval, "GenerationEval", _FailGenerationEval)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_eval.py",
            "--dataset", "book",
            "--backend-url", "http://test",
            "--judge-model", "ollama/fake-judge",
        ],
    )

    run_eval.main()

    eval_kind, _, metrics, _ = history[0]
    assert eval_kind == "retrieval"
    assert metrics["faithfulness"] is None
    assert metrics["qa_failed_calls"] == 2


def test_not_found_counts_as_declined_not_failed(monkeypatch):
    """A /qa not_found response is a real product decline, not a harness failure:
    it must land in qa_not_found_calls, not qa_failed_calls."""
    history: list[tuple] = []
    judged_batches: list[list[dict]] = []
    _wire_common(monkeypatch, history)

    # Q1 answers, Q2 declines (not_found), so 1 answered + 1 declined + 0 failed.
    def _qa(url, question, model, doc_id):
        if question == "Q1":
            return {"answer": "a real answer here", "citations": []}
        return {"not_found": True}

    monkeypatch.setattr(run_eval, "post_qa", _qa)

    class _CaptureGenerationEval:
        def run(self, samples, judge_model):
            judged_batches.append(samples)
            return {
                "faithfulness": 0.8, "answer_relevance": 0.7,
                "context_precision": None, "context_recall": None,
                "judge_failed_calls": 0, "judge_total_calls": 2,
            }

    monkeypatch.setattr(run_eval, "GenerationEval", _CaptureGenerationEval)
    monkeypatch.setattr(
        sys, "argv",
        ["run_eval.py", "--dataset", "book", "--backend-url", "http://test",
         "--judge-model", "ollama/fake-judge"],
    )

    run_eval.main()

    _, _, metrics, _ = history[0]
    assert metrics["qa_answered_calls"] == 1
    assert metrics["qa_not_found_calls"] == 1
    assert metrics["qa_failed_calls"] == 0
    # only the answered question is judged
    assert len(judged_batches[0]) == 1
    assert judged_batches[0][0]["question"] == "Q1"
