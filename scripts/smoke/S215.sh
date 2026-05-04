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
    parse_claims_with_citations,
)
from evals.lib.scoring_history import append_history
from run_eval import THRESHOLDS

answer = "Alice opened the small door with a key [1]. She drank from the bottle [2][3]."
pairs = parse_claims_with_citations(answer)
assert pairs == [
    ("Alice opened the small door with a key.", 0),
    ("She drank from the bottle.", 1),
    ("She drank from the bottle.", 2),
]

verdicts = iter(["yes", "yes", "partial", "no"])
rate = compute_citation_support_rate(
    [("c1", "x"), ("c2", "x"), ("c3", "x"), ("c4", "x")],
    judge=lambda claim, chunk: next(verdicts),
)
assert rate == 0.625, rate
assert THRESHOLDS["citation_support_rate"] == 0.80
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
