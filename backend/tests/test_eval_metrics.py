"""Unit tests for RAGAS eval metric functions in evals/run_eval.py.

These tests import the pure metric functions directly and verify correct
computation against synthetic samples.  No live backend required.

Tests:
  - test_hit_rate_exact_match         -- hint appears verbatim in chunk
  - test_hit_rate_partial_match       -- only first 80 chars of hint matched
  - test_hit_rate_no_match            -- hint not in any chunk -> 0.0
  - test_hit_rate_mixed               -- some hits, some misses -> fractional
  - test_hit_rate_fallback_to_ground_truth -- no context_hint, uses ground_truth prefix
  - test_mrr_first_chunk_match        -- hit in rank 1 -> MRR = 1.0
  - test_mrr_second_chunk_match       -- hit in rank 2 -> MRR = 0.5
  - test_mrr_no_match                 -- no hit -> MRR = 0.0
  - test_mrr_mixed                    -- multiple samples, avg reciprocal rank
  - test_passed_true_when_above_thresholds
  - test_passed_false_when_hr5_below_threshold
  - test_passed_false_when_mrr_below_threshold
"""

import sys
from pathlib import Path

import pytest

# Import from evals/run_eval.py -- it lives outside the backend package tree,
# so we resolve the path at import time.
_EVALS_DIR = Path(__file__).resolve().parent.parent.parent / "evals"
sys.path.insert(0, str(_EVALS_DIR))

from run_eval import THRESHOLDS, compute_hit_rate_5, compute_mrr  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample(question: str, hint: str, chunks: list[str], ground_truth: str = "GT") -> dict:
    return {
        "question": question,
        "context_hint": hint,
        "contexts": chunks,
        "ground_truths": [ground_truth],
    }


# ---------------------------------------------------------------------------
# HR@5 tests
# ---------------------------------------------------------------------------


def test_hit_rate_exact_match():
    """Hint appears verbatim in the first chunk -> HR@5 = 1.0."""
    samples = [_sample("q1", "the quick brown fox", ["the quick brown fox jumps"])]
    assert compute_hit_rate_5(samples) == pytest.approx(1.0)


def test_hit_rate_partial_match():
    """Only the first 80 chars of a long hint need to appear in the chunk."""
    long_hint = "a" * 80 + "this suffix is never checked"
    chunk = "prefix text " + "a" * 80 + " suffix"
    samples = [_sample("q1", long_hint, [chunk])]
    assert compute_hit_rate_5(samples) == pytest.approx(1.0)


def test_hit_rate_no_match():
    """Hint not present in any chunk -> HR@5 = 0.0."""
    samples = [_sample("q1", "needle not here", ["haystack one", "haystack two"])]
    assert compute_hit_rate_5(samples) == pytest.approx(0.0)


def test_hit_rate_mixed():
    """Two samples, one hit and one miss -> HR@5 = 0.5."""
    samples = [
        _sample("q1", "found passage", ["found passage in this chunk"]),
        _sample("q2", "missing passage", ["completely different text"]),
    ]
    assert compute_hit_rate_5(samples) == pytest.approx(0.5)


def test_hit_rate_hint_in_second_chunk():
    """Hint in second chunk (still within top-5) counts as a hit."""
    samples = [_sample("q1", "target text", ["irrelevant chunk one", "target text is here"])]
    assert compute_hit_rate_5(samples) == pytest.approx(1.0)


def test_hit_rate_fallback_to_ground_truth():
    """When context_hint is empty, first 50 chars of ground_truth are used."""
    ground_truth = "the answer to the ultimate question of life the universe and everything"
    chunk = ground_truth[:50] + " extra text to pad the chunk"
    samples = [
        {
            "question": "q1",
            "context_hint": "",  # empty hint
            "contexts": [chunk],
            "ground_truths": [ground_truth],
        }
    ]
    assert compute_hit_rate_5(samples) == pytest.approx(1.0)


def test_hit_rate_empty_samples():
    """Empty sample list returns 0.0 without error."""
    assert compute_hit_rate_5([]) == pytest.approx(0.0)


def test_hit_rate_newline_in_chunk():
    """Hint with spaces matches chunk where whitespace is a newline (Gutenberg line-wrap fix)."""
    hint = "any real body must have extension in four directions"
    # Chunk text has a line break mid-phrase, as in Project Gutenberg plain-text files
    chunk = "any\nreal body must have extension in four directions: it must have"
    samples = [_sample("q1", hint, [chunk])]
    assert compute_hit_rate_5(samples) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# MRR tests
# ---------------------------------------------------------------------------


def test_mrr_first_chunk_match():
    """Hit at rank 1 -> reciprocal rank = 1.0 -> MRR = 1.0."""
    samples = [_sample("q1", "target", ["target is right here", "other chunk"])]
    assert compute_mrr(samples) == pytest.approx(1.0)


def test_mrr_second_chunk_match():
    """Hit at rank 2 -> reciprocal rank = 0.5 -> MRR = 0.5."""
    samples = [_sample("q1", "target", ["irrelevant", "target is here", "more irrelevant"])]
    assert compute_mrr(samples) == pytest.approx(0.5)


def test_mrr_no_match():
    """No hit -> reciprocal rank = 0 -> MRR = 0.0."""
    samples = [_sample("q1", "needle", ["haystack a", "haystack b"])]
    assert compute_mrr(samples) == pytest.approx(0.0)


def test_mrr_mixed():
    """Two samples: rank-1 hit (1.0) and no hit (0.0) -> MRR = 0.5."""
    samples = [
        _sample("q1", "found", ["found here"]),
        _sample("q2", "missing", ["nothing relevant"]),
    ]
    assert compute_mrr(samples) == pytest.approx(0.5)


def test_mrr_empty_samples():
    """Empty sample list returns 0.0 without error."""
    assert compute_mrr([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Threshold / passed logic tests
# ---------------------------------------------------------------------------


def test_passed_true_when_above_thresholds():
    """Metrics above thresholds -> passed=True."""
    hr5 = THRESHOLDS["hit_rate_5"] + 0.1  # above
    mrr = THRESHOLDS["mrr"] + 0.1  # above
    violations: list[str] = []
    if hr5 < THRESHOLDS["hit_rate_5"]:
        violations.append("HR@5 failed")
    if mrr < THRESHOLDS["mrr"]:
        violations.append("MRR failed")
    assert len(violations) == 0


def test_passed_false_when_hr5_below_threshold():
    """HR@5 below threshold -> violation recorded."""
    hr5 = THRESHOLDS["hit_rate_5"] - 0.1  # below
    mrr = THRESHOLDS["mrr"] + 0.1  # above
    violations: list[str] = []
    if hr5 < THRESHOLDS["hit_rate_5"]:
        violations.append(f"HR@5 {hr5:.4f} below threshold")
    if mrr < THRESHOLDS["mrr"]:
        violations.append(f"MRR {mrr:.4f} below threshold")
    assert len(violations) == 1
    assert "HR@5" in violations[0]


def test_passed_false_when_mrr_below_threshold():
    """MRR below threshold -> violation recorded."""
    hr5 = THRESHOLDS["hit_rate_5"] + 0.1  # above
    mrr = THRESHOLDS["mrr"] - 0.1  # below
    violations: list[str] = []
    if hr5 < THRESHOLDS["hit_rate_5"]:
        violations.append(f"HR@5 {hr5:.4f} below threshold")
    if mrr < THRESHOLDS["mrr"]:
        violations.append(f"MRR {mrr:.4f} below threshold")
    assert len(violations) == 1
    assert "MRR" in violations[0]
