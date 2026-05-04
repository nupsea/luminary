"""Unit tests for citation grounding metrics (S215)."""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.citation_metrics import (  # noqa: E402
    compute_citation_support_rate,
    parse_claims_with_citations,
)


def test_parse_claims_with_citations_extracts_claim_index_pairs():
    answer = (
        "Alice found a small key on the table [1]. "
        "The bottle said DRINK ME, and she checked it was not poison [2]. "
        "This sentence has no citation. "
        "The rabbit carried a watch [3][4]."
    )

    pairs = parse_claims_with_citations(answer)

    assert pairs == [
        ("Alice found a small key on the table.", 0),
        ("The bottle said DRINK ME, and she checked it was not poison.", 1),
        ("The rabbit carried a watch.", 2),
        ("The rabbit carried a watch.", 3),
    ]


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
