"""The quality gate itself: what makes a run fail, and what it records.

`test_run_eval_generation_flow.py` covers the harness mechanics -- who gets
scored, against which contexts. Nothing covered the verdict. Every test there
destructures the history row as `(eval_kind, model, metrics, _)`, discarding the
`passed` flag, and no test in the repo passed `--assert-thresholds` or asserted a
`SystemExit`. So a run that measured nothing could record `passed: true` and exit
0 with the suite green -- 166 history rows were written under that rule.

These tests assert the verdict and the exit status, which is the only thing that
makes a threshold a gate rather than a printed number.
"""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import run_eval

_GOLDEN = [
    {
        "question": "Q1",
        "ground_truth_answer": "GOLD ONE",
        "context_hint": "hint one",
        "source_file": "",
        "source_document_id": "doc-1",
    },
    {
        "question": "Q2",
        "ground_truth_answer": "GOLD TWO",
        "context_hint": "hint two",
        "source_file": "",
        "source_document_id": "doc-1",
    },
]

# "hint one" is inside it and "hint two" is not, so retrieval scores 0.5/0.5 --
# above the book floors of 0.50/0.35, and every generation case below therefore
# fails on the generation metric alone.
_CHUNK = "chunk with hint one inside"


class _Nli:
    """Stand-in for HHEM. `score` None reproduces a model that failed to load."""

    score: float | None = 0.95

    def run(self, samples, **kwargs):
        answered = [s for s in samples if s.get("answer", "").strip()]
        if not answered:
            return {"faithfulness": None, "faithfulness_model": None}
        return {"faithfulness": type(self).score, "faithfulness_model": "fake/hhem"}


def _wire(monkeypatch, history, *, qa=None, judge_scores=None, nli_score=0.95):
    _Nli.score = nli_score
    monkeypatch.setattr(run_eval, "NliFaithfulnessEval", _Nli)
    monkeypatch.setattr(run_eval, "load_golden", lambda dataset: [dict(r) for r in _GOLDEN])
    monkeypatch.setattr(run_eval, "load_manifest", lambda: {})
    # Unpatched, these reach the network. `http://test` resolves on some networks
    # and blackholes rather than failing fast, so each probe costs its full 10s
    # connect timeout -- resolve_backend_base alone tries two candidates. That put
    # every test in this file at a uniform 30s regardless of what it asserts.
    monkeypatch.setattr(run_eval, "is_document_alive", lambda *a, **k: True)
    monkeypatch.setattr(run_eval, "resolve_backend_base", lambda url: url)
    monkeypatch.setattr(run_eval, "require_backend", lambda *a, **k: None)
    monkeypatch.setattr(run_eval, "search_chunks", lambda *a, **k: [_CHUNK])
    monkeypatch.setattr(
        run_eval,
        "_lib_append_history",
        lambda dataset, model, metrics, passed, eval_kind, environment=None: history.append(
            {
                "kind": eval_kind,
                "metrics": metrics,
                "passed": passed,
                "environment": environment,
            }
        ),
    )
    monkeypatch.setattr(run_eval, "_lib_store_results", lambda *a, **k: None)
    if qa is not None:
        monkeypatch.setattr(run_eval, "post_qa", qa)
    if judge_scores is not None:

        class _Judge:
            def run(self, samples, judge_model):
                return judge_scores

        monkeypatch.setattr(run_eval, "GenerationEval", _Judge)


def _run(monkeypatch, *argv):
    monkeypatch.setattr(
        sys, "argv", ["run_eval.py", "--dataset", "book", "--backend-url", "http://test", *argv]
    )
    run_eval.main()


def _answers(url, question, model, doc_id):
    return {"answer": f"GENERATED::{question}", "context_chunks": [_CHUNK]}


# A violation has to stop the run, not just print


def test_a_retrieval_violation_exits_non_zero(monkeypatch):
    history: list[dict] = []
    _wire(monkeypatch, history)
    monkeypatch.setattr(run_eval, "search_chunks", lambda *a, **k: ["nothing relevant here"])

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--assert-thresholds")

    assert exc.value.code == 1
    assert history[0]["passed"] is False


def test_a_clean_run_passes_and_does_not_exit(monkeypatch):
    history: list[dict] = []
    _wire(monkeypatch, history)

    _run(monkeypatch, "--assert-thresholds")

    assert history[0]["passed"] is True
    assert history[0]["metrics"]["hit_rate_5"] == 0.5


def test_a_violation_is_recorded_even_without_assert_thresholds(monkeypatch):
    """The flag decides whether the run *exits*, never whether it passed.

    `passed` is what lands in scores_history.jsonl, so a run that recorded a pass
    it did not earn poisons every later comparison against that history.
    """
    history: list[dict] = []
    _wire(monkeypatch, history)
    monkeypatch.setattr(run_eval, "search_chunks", lambda *a, **k: ["nothing relevant here"])

    _run(monkeypatch)

    assert history[0]["passed"] is False


# Requested but uncomputed is a failure, not a skip


def test_faithfulness_that_could_not_be_scored_fails(monkeypatch):
    """Answers existed, so the NLI scorer was asked. `None` means it broke."""
    history: list[dict] = []
    _wire(monkeypatch, history, qa=_answers, nli_score=None)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--generate", "--assert-thresholds")

    assert exc.value.code == 1
    assert history[0]["passed"] is False
    assert history[0]["metrics"]["faithfulness"] is None


def test_answer_relevance_that_the_judge_could_not_score_fails(monkeypatch):
    history: list[dict] = []
    _wire(
        monkeypatch,
        history,
        qa=_answers,
        judge_scores={
            "answer_relevance": None,
            "context_precision": None,
            "context_recall": None,
            "judge_failed_calls": 2,
            "judge_total_calls": 2,
        },
    )

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--judge-model", "ollama/fake", "--assert-thresholds")

    assert exc.value.code == 1
    assert history[0]["passed"] is False


def test_generation_requested_but_no_answers_fails(monkeypatch):
    """Retrieval can look healthy while the generation half measured nothing."""
    history: list[dict] = []
    _wire(monkeypatch, history, qa=lambda *a, **k: {})

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--judge-model", "ollama/fake", "--assert-thresholds")

    assert exc.value.code == 1
    assert history[0]["passed"] is False


# Product-outcome metrics: answering at all, and citing what it answered


def test_declining_answerable_questions_fails(monkeypatch):
    """Every golden question was cross-verified answerable by two models.

    So a decline is the product failing a question that has an answer. Retrieval
    is healthy in this run; nothing but `answer_rate` sees the failure.
    """
    history: list[dict] = []

    def _declines(url, question, model, doc_id):
        if question == "Q1":
            return {"answer": "a real answer", "citations": [{"excerpt": _CHUNK}]}
        return {"not_found": True}

    _wire(monkeypatch, history, qa=_declines)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--generate", "--assert-thresholds")

    assert exc.value.code == 1
    assert history[0]["metrics"]["answer_rate"] == 0.5
    assert history[0]["metrics"]["qa_not_found_calls"] == 1
    assert history[0]["passed"] is False


def test_uncited_answers_fail(monkeypatch):
    """An answer with no source is unverifiable, which is the product's claim."""
    history: list[dict] = []
    _wire(
        monkeypatch,
        history,
        qa=lambda url, question, model, doc_id: {"answer": f"GENERATED::{question}"},
    )

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--generate", "--assert-thresholds")

    assert exc.value.code == 1
    assert history[0]["metrics"]["citation_coverage"] == 0.0
    assert history[0]["metrics"]["answer_rate"] == 1.0


def test_fully_answered_and_cited_passes(monkeypatch):
    history: list[dict] = []
    _wire(
        monkeypatch,
        history,
        qa=lambda url, question, model, doc_id: {
            "answer": f"GENERATED::{question}",
            "citations": [{"excerpt": "supporting text"}],
            "context_chunks": [_CHUNK],
        },
    )

    _run(monkeypatch, "--generate", "--assert-thresholds")

    assert history[0]["metrics"]["answer_rate"] == 1.0
    assert history[0]["metrics"]["citation_coverage"] == 1.0
    assert history[0]["passed"] is True


# A metric nobody asked for stays a skip


def test_a_retrieval_only_run_is_not_failed_by_absent_generation_metrics(monkeypatch):
    """The default run generates no answers, so faithfulness is absent, not broken.

    This is the line the fix must not cross: `None` fails only where something was
    asked to produce a number and did not.
    """
    history: list[dict] = []
    _wire(monkeypatch, history)

    _run(monkeypatch, "--assert-thresholds")

    assert history[0]["kind"] == "retrieval"
    assert history[0]["metrics"]["faithfulness"] is None
    assert history[0]["passed"] is True


# Coverage attribution: why an answer carried no source


def _answers_with_drops(url, question, model, doc_id):
    """One answer keeps a citation, the other had its only citation removed."""
    if question == "Q1":
        return {
            "answer": "A1",
            "context_chunks": [_CHUNK],
            "citations": [{"excerpt": "hint one"}],
            "citations_dropped": 0,
        }
    return {
        "answer": "A2",
        "context_chunks": [_CHUNK],
        "citations": [],
        "citations_dropped": 2,
    }


def test_coverage_records_why_an_answer_was_uncited(monkeypatch):
    """citation_coverage alone cannot separate 'the model named no source' from
    'the sources it named were ungrounded and removed'. Both land on the same
    ratio, and only one of them is a grounding failure."""
    history: list[dict] = []
    _wire(monkeypatch, history, qa=_answers_with_drops, judge_scores={"answer_relevance": 0.9})
    with pytest.raises(SystemExit):
        _run(monkeypatch, "--judge-model", "test/judge", "--assert-thresholds")
    metrics = history[-1]["metrics"]
    assert metrics["citation_coverage"] == 0.5
    assert metrics["citations_dropped"] == 2
    assert metrics["uncited_answers"] == 1


def test_drop_count_is_zero_when_qa_reports_none(monkeypatch):
    """A backend that never removed a citation must report 0, not None -- an
    absent count would read as 'not measured' under I-32."""
    history: list[dict] = []
    _wire(monkeypatch, history, qa=_answers, judge_scores={"answer_relevance": 0.9})
    with pytest.raises(SystemExit):
        _run(monkeypatch, "--judge-model", "test/judge", "--assert-thresholds")
    assert history[-1]["metrics"]["citations_dropped"] == 0


# What produced the number is part of the record (E5)


def test_a_run_records_the_environment_that_produced_it(monkeypatch):
    """Metrics alone cannot be compared across runs: re-ingesting one document has
    moved an untouched document's MRR by as much as a model change did. The row
    carries the build, the resolved models and the corpus fingerprint, or it
    carries the reason it could not."""
    history: list[dict] = []
    _wire(monkeypatch, history)
    monkeypatch.setattr(
        run_eval,
        "capture_environment",
        lambda url, **kw: {
            "backend_version": "9.9.9",
            "chat_model": "ollama/test",
            "library": {"documents": 3, "chunks": 41},
            **kw,
        },
    )
    _run(monkeypatch)

    env = history[-1]["environment"]
    assert env["library"] == {"documents": 3, "chunks": 41}
    assert env["chat_model"] == "ollama/test"
    # Knobs the backend cannot know, recorded by the runner itself.
    assert env["scope"] == "scoped"
    assert env["rerank"] is False


def test_unreachable_backend_records_why_provenance_is_missing(monkeypatch):
    """A failed capture states the failure. A blank would be indistinguishable
    from a row written before provenance existed."""
    history: list[dict] = []
    _wire(monkeypatch, history)
    _run(monkeypatch)

    env = history[-1]["environment"]
    assert "capture_error" in env
    assert env.get("backend_version") is None
