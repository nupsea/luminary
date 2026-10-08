"""A route the heuristic claims at or above LLM_FALLBACK_BELOW is one it gets right.

Above the threshold nothing checks the heuristic, so a confident misroute has no
recourse on any host. That was 31 of the 168 routes it claimed across the intent
goldens when the bare question openers ("which", "what does", "how does") claimed
0.8-0.85; with openers at OPENER_CONFIDENCE it claims 93 and misroutes none.

Deterministic and backend-free: it reads the goldens `make eval-intent` scores,
but only the heuristic, so it gates in CI where the eval cannot run.
"""

import json
from pathlib import Path

import pytest

from app.services.intent import LLM_FALLBACK_BELOW, classify_intent_heuristic

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden"
DATASETS = ("intents", "intents_adversarial", "intents_heldout")
ROUTE = {"summary": "summary", "relational": "graph", "comparative": "comparative"}

# Bracketed by the openers claiming 0.8 (137 of 168 claims right, 0.8155) and by
# openers below the threshold (93 of 93): two new misroutes in 93 claims pass, three fail.
MIN_CONFIDENT_PRECISION = 0.97
# A heuristic that defers everything is trivially precise and sends every message
# to the LLM. Bracketed by deferring everything (0) and today's 93 of 239 (0.389).
MIN_CONFIDENT_SHARE = 0.25


def _rows():
    for name in DATASETS:
        with (GOLDEN / f"{name}.jsonl").open() as f:
            yield from (json.loads(line) for line in f if line.strip())


def _claims():
    out = []
    for row in _rows():
        intent, confidence = classify_intent_heuristic(row["question"])
        if confidence >= LLM_FALLBACK_BELOW:
            out.append((row, ROUTE.get(intent, "search")))
    return out


@pytest.fixture(scope="module")
def claims():
    return _claims()


def test_a_confident_route_is_a_right_route(claims):
    wrong = [
        f"{row['question']!r}: claimed {got}, want {row['expected_route']}"
        for row, got in claims
        if got != row["expected_route"]
    ]
    precision = 1 - len(wrong) / len(claims)
    assert precision >= MIN_CONFIDENT_PRECISION, "\n".join(wrong)


def test_the_heuristic_still_decides_what_it_can(claims):
    share = len(claims) / sum(1 for _ in _rows())
    assert share >= MIN_CONFIDENT_SHARE, f"heuristic claims only {share:.3f} of rows"
