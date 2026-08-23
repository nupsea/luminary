#!/usr/bin/env bash
# Smoke test for S215: citation grounding eval.
#
# Verifies without requiring a live backend:
#   1. run_eval.py documents --check-citations.
#   2. citation_metrics exposes parser, judge function, and support-rate aggregation.
#   3. scores_history entries can persist citation_support_rate with eval_kind=citation.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_eval.py --help)"
grep -q -- "--check-citations" <<<"$HELP"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

from evals.lib.citation_metrics import (
    compute_citation_support_rate,
    judge_citation,
    pair_answer_with_citations,
)
from evals.lib.scoring_history import append_history
from run_eval import THRESHOLDS

# `parse_claims_with_citations` split prose on inline [N] markers and attributed
# each claim to one citation. The product has never emitted those markers -- it
# returns prose plus a JSON citations block -- so that metric scored None in all
# 285 recorded runs, and attributing claims anyway would invent a link the answer
# never made. Each citation is judged against the whole answer now.
answer = "Alice opened the small door with a key. She drank from the bottle."
pairs = pair_answer_with_citations(
    answer,
    [
        {"text": "a golden key lay on the table"},
        {"excerpt": "she drank it off and found it very nice"},
        {"text": ""},          # no excerpt to judge -- dropped
        "not a citation object",
    ],
)
assert pairs == [
    (answer, "a golden key lay on the table"),
    (answer, "she drank it off and found it very nice"),
], pairs

verdicts = iter(["yes", "yes", "partial", "no"])
rate = compute_citation_support_rate(
    [("c1", "x"), ("c2", "x"), ("c3", "x"), ("c4", "x")],
    judge=lambda claim, chunk: next(verdicts),
)
assert rate == 0.625, rate
# 0.80 was a chosen number. The floor is derived: (mean - 3sd) of four runs on a
# frozen build, rounded down to 0.05, which put it at 0.45 -- a collapse detector,
# not a quality bar, and run_eval.py carries the measurements.
assert THRESHOLDS["citation_support_rate"] == 0.45, THRESHOLDS["citation_support_rate"]
assert callable(judge_citation)

with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "scores.jsonl"
    append_history(
        "book_alice",
        "ollama/test",
        {"citation_support_rate": rate},
        False,
        eval_kind="citation",
        path=target,
    )
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "citation"
    assert row["citation_support_rate"] == 0.625

print("PASS: S215 -- citation parser, support-rate aggregation, threshold, and history persistence are green")
PY
