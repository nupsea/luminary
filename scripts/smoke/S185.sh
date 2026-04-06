#!/usr/bin/env bash
# Smoke test for S185: Simplified Study tab.
# Pure frontend refactor -- verify backend endpoints used by InsightsAccordion are reachable.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expected="$3"
  TMPFILE=$(mktemp /tmp/s185_XXXXXX)
  HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$url")
  if [ "$HTTP" != "$expected" ]; then
    echo "FAIL: $desc — expected $expected, got $HTTP"
    cat "$TMPFILE"
    rm -f "$TMPFILE"
    FAIL=$((FAIL + 1))
    return
  fi
  rm -f "$TMPFILE"
  PASS=$((PASS + 1))
  echo "PASS: $desc"
}

# 1. Health check
check "Health check" "${BASE}/health" "200"

# 2. Flashcard search (card list loads)
check "GET /flashcards/search" "${BASE}/flashcards/search" "200"

# 3. Bloom audit endpoint (used by InsightsAccordion DeckHealthPanel)
# No documents ingested in smoke, so dummy doc_id returns 404 or 200
TMPFILE=$(mktemp /tmp/s185_XXXXXX)
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/flashcards/audit/smoke-doc-s185")
if [ "$HTTP" = "200" ] || [ "$HTTP" = "404" ]; then
  echo "PASS: GET /flashcards/audit/:id — reachable ($HTTP)"
  PASS=$((PASS + 1))
else
  echo "FAIL: GET /flashcards/audit/:id — expected 200 or 404, got $HTTP"
  FAIL=$((FAIL + 1))
fi
rm -f "$TMPFILE"

# 4. Health report endpoint (used by InsightsAccordion HealthReportPanel)
TMPFILE=$(mktemp /tmp/s185_XXXXXX)
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/flashcards/health/smoke-doc-s185")
if [ "$HTTP" = "200" ] || [ "$HTTP" = "404" ]; then
  echo "PASS: GET /flashcards/health/:id — reachable ($HTTP)"
  PASS=$((PASS + 1))
else
  echo "FAIL: GET /flashcards/health/:id — expected 200 or 404, got $HTTP"
  FAIL=$((FAIL + 1))
fi
rm -f "$TMPFILE"

# 5. Struggling cards endpoint (used by InsightsAccordion StrugglingPanel)
TMPFILE=$(mktemp /tmp/s185_XXXXXX)
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/study/struggling?document_id=smoke-doc-s185")
if [ "$HTTP" = "200" ] || [ "$HTTP" = "404" ]; then
  echo "PASS: GET /study/struggling — reachable ($HTTP)"
  PASS=$((PASS + 1))
else
  echo "FAIL: GET /study/struggling — expected 200 or 404, got $HTTP"
  FAIL=$((FAIL + 1))
fi
rm -f "$TMPFILE"

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "S185 smoke: ALL PASSED"
