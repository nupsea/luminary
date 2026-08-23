#!/usr/bin/env bash
# Smoke test for S88: the book golden datasets are whole and correctly sourced.
#
# This script was written when one `book.jsonl` held all three books, and it
# asserted >= 70 entries with >= 20 each from Alice and the Odyssey. The corpus
# was since split one dataset per book -- `book_alice`, `book_time_machine`,
# `book_frankenstein`, `odyssey` -- and each carries 40 questions drawn from a
# single source. The old assertions therefore reported a shrunken corpus while
# the corpus had in fact grown from 70 questions to 200.
#
# Verifies, for every book dataset registered in run_eval.VALID_DATASETS:
#   1. the file exists and is non-trivial
#   2. every question names exactly one source_file, and that file is under DATA
#   3. ruff passes and the corpus test module is present
#
# Does NOT run the slow pytest suite (that requires real ML).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "S88 smoke: checking the book golden datasets"
cd "$REPO_ROOT"
python3 - <<'EOF'
import json
from pathlib import Path

# One dataset per book. Each is the whole question set for that book, so a file
# mixing sources means a generator wrote questions about text it was not given.
EXPECTED = {
    "book": "DATA/books/time_machine.txt",
    "book_time_machine": "DATA/books/time_machine.txt",
    "book_alice": "DATA/books/alice_in_wonderland.txt",
    "book_frankenstein": "DATA/books/frankenstein.txt",
    "odyssey": "DATA/books/the_odyssey.txt",
}

# The floor is a collapse detector, not a size target: a book dataset that has
# lost most of its questions is measuring something other than what its history
# measured. Every one of these currently holds 40.
MINIMUM = 20

for name, source in EXPECTED.items():
    path = Path("evals/golden") / f"{name}.jsonl"
    assert path.exists(), f"{path} is missing"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) >= MINIMUM, (
        f"{name}.jsonl has {len(rows)} questions, below the {MINIMUM} floor"
    )
    sources = {r.get("source_file") for r in rows}
    assert sources == {source}, (
        f"{name}.jsonl draws on {sorted(sources)}; it must be exactly [{source}]"
    )
    missing_q = [r for r in rows if not r.get("question")]
    assert not missing_q, f"{name}.jsonl has {len(missing_q)} rows with no question"
    print(f"  PASS: {name}.jsonl -- {len(rows)} questions, all from {source}")

# The names above have to stay in step with what the harness will actually run.
# Read the list rather than importing run_eval, which pulls httpx and the rest of
# the harness in to answer a question about a literal.
import ast

tree = ast.parse(Path("evals/run_eval.py").read_text())
valid = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
        getattr(t, "id", None) == "VALID_DATASETS" for t in node.targets
    ):
        valid = [e.value for e in node.value.elts]
assert valid, "VALID_DATASETS not found in evals/run_eval.py"

unregistered = sorted(set(EXPECTED) - set(valid))
assert not unregistered, f"{unregistered} are not in VALID_DATASETS -- run_eval cannot run them"
print(f"  PASS: all {len(EXPECTED)} book datasets are registered in run_eval")
EOF

echo "S88 smoke: ruff check"
cd "$REPO_ROOT/backend" && uv run ruff check . --quiet
echo "PASS: ruff check"

echo "S88 smoke: test_corpus_qa.py exists"
if [ ! -f "$REPO_ROOT/backend/tests/test_corpus_qa.py" ]; then
  echo "FAIL: backend/tests/test_corpus_qa.py not found"
  exit 1
fi
echo "PASS: test_corpus_qa.py exists"

echo "S88 smoke: all checks passed"
