"""Unit tests for citation grounding metrics (S215)."""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.citation_metrics import (  # noqa: E402
    compute_citation_support_rate,
    pair_answer_with_citations,
)


def test_each_shown_citation_is_paired_with_the_answer():
    """The product returns prose plus a citations list, never [N] markers.

    So the measurable claim is per-citation: every source chip shown under an
    answer should support what the answer said. The previous metric split prose
    on [N] and scored None in all 285 recorded runs.
    """
    answer = "Alice found a key. The bottle said DRINK ME."
    citations = [
        {"excerpt": "a tiny golden key", "page": 12},
        {"text": "the bottle was labelled DRINK ME", "page": 13},
    ]

    assert pair_answer_with_citations(answer, citations) == [
        ("Alice found a key. The bottle said DRINK ME.", "a tiny golden key"),
        ("Alice found a key. The bottle said DRINK ME.", "the bottle was labelled DRINK ME"),
    ]


def test_citations_without_usable_text_are_not_paired():
    """A placeholder chip has no excerpt to judge, so it cannot be scored."""
    answer = "Some answer."

    assert pair_answer_with_citations(answer, [{"page": 0}, {"excerpt": "   "}, "junk"]) == []


def test_an_empty_answer_pairs_with_nothing():
    assert pair_answer_with_citations("   ", [{"excerpt": "real text"}]) == []


def test_compute_citation_support_rate_weights_partial_verdicts():
    pairs = [
        ("claim 1", "chunk 1"),
        ("claim 2", "chunk 2"),
        ("claim 3", "chunk 3"),
        ("claim 4", "chunk 4"),
    ]
    verdicts = iter(["yes", "yes", "partial", "no"])

    rate = compute_citation_support_rate(
        pairs,
        judge=lambda claim, chunk: next(verdicts),  # noqa: ARG005
    )

    assert rate == pytest.approx(0.625)


def test_compute_citation_support_rate_returns_none_without_pairs():
    assert compute_citation_support_rate([], judge=lambda claim, chunk: "yes") is None


def test_an_unusable_verdict_is_a_judge_failure_not_a_zero(monkeypatch):
    """A judge that answers in an unrecognised shape has told us nothing.

    `judge_citation` used to return "no" for it, which scores 0 -- recording a
    judge failure as a product failure, and silently, because the caller's
    failure counter never sees a value that was returned normally.
    """
    import evals.lib.citation_metrics as cm

    class _Msg:
        content = '{"verdict": "maybe"}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    monkeypatch.setattr(
        cm, "judge_citation", cm.judge_citation
    )  # keep the real function under test
    monkeypatch.setitem(
        sys.modules, "litellm", type("L", (), {"completion": staticmethod(lambda **kw: _Resp())})
    )

    with pytest.raises(ValueError, match="unusable verdict"):
        cm.judge_citation("an answer", "a chunk", "some/model")


def test_a_failing_judge_lowers_nothing_and_is_counted():
    """The rate is computed over successful judgements only.

    One unusable verdict among two must not drag the rate to 0.5; it must leave
    the rate at the one judgement that worked.
    """
    calls = {"n": 0}

    def _judge(_claim, _chunk):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("citation judge returned an unusable verdict: 'maybe'")
        return "yes"

    rate = compute_citation_support_rate(
        [("a", "x"), ("a", "y")],
        judge=_judge,
    )
    assert rate == 1.0, "a failed judge call must be excluded, not scored zero"


def test_every_judge_failing_yields_none_rather_than_zero():
    def _judge(_claim, _chunk):
        raise ValueError("unusable")

    assert compute_citation_support_rate([("a", "x")], judge=_judge) is None
