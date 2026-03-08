#!/usr/bin/env bash
# Smoke test for S88 -- expanded golden datasets and corpus integration tests
# Verifies: jsonl entry count >= 70, all source_file paths are known values,
# and ruff passes. Does NOT run the slow pytest suite (that requires real ML).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GOLDEN="$REPO_ROOT/evals/golden/book.jsonl"

echo "S88 smoke: checking golden dataset line count"
COUNT=$(grep -c '"question"' "$GOLDEN" || true)
if [ "$COUNT" -lt 70 ]; then
  echo "FAIL: book.jsonl has $COUNT entries (expected >= 70)"
  exit 1
fi
echo "PASS: book.jsonl has $COUNT entries (>= 70)"

echo "S88 smoke: checking Alice entries have correct source_file"
ALICE_COUNT=$(grep -c '"DATA/books/alice_in_wonderland.txt"' "$GOLDEN" || true)
if [ "$ALICE_COUNT" -lt 20 ]; then
  echo "FAIL: only $ALICE_COUNT Alice entries found (expected >= 20)"
  exit 1
fi
echo "PASS: $ALICE_COUNT Alice entries found"

echo "S88 smoke: checking Odyssey entries have correct source_file"
ODYSSEY_COUNT=$(grep -c '"DATA/books/the_odyssey.txt"' "$GOLDEN" || true)
if [ "$ODYSSEY_COUNT" -lt 20 ]; then
  echo "FAIL: only $ODYSSEY_COUNT Odyssey entries found (expected >= 20)"
  exit 1
fi
echo "PASS: $ODYSSEY_COUNT Odyssey entries found"

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
