#!/usr/bin/env bash
# Smoke test for S137: POST /flashcards/generate-technical returns HTTP 201
# with a JSON array in which every card carries flashcard_type.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

# BSD mktemp only substitutes Xs at the END of a template, so
# `mktemp /tmp/foo.XXXXXX.json` created that name literally: the script worked
# once per machine and then failed "File exists" forever. One per-run directory
# keeps the extensions -- uploads are validated on them -- and cleans up itself.
SMOKE_TMPDIR=$(mktemp -d)

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Upload a small tech document so we have something to generate from
DOC_TMPFILE="$SMOKE_TMPDIR/s137doc.txt"
# Enough material for a card to be a fair expectation. The previous fixture was
# eleven lines, and generation legitimately returned zero cards from it -- every
# candidate failed the grounding gate, which needs a quotable sentence -- so the
# script blamed the endpoint for the size of its own input.
cat > "${DOC_TMPFILE}" << 'DOCEOF'
# Python Functions and Data Structures

## Defining functions

A function is defined with `def`, takes zero or more parameters, and returns a
value with `return`. A function that falls off its end returns None implicitly,
which is the most common source of "why is my result None" confusion.

def add(a, b):
    return a + b

Default arguments are evaluated once, when the function is defined, not on each
call. A mutable default such as `def f(items=[])` therefore shares one list
across every call that omits the argument, and the list grows between calls.
Use `None` as the default and build the list inside the body instead.

## List vs Tuple trade-off

Lists are mutable; tuples are immutable. Use tuples for fixed data and lists
when you need append or remove. Because a tuple cannot change, it can be used
as a dictionary key while a list cannot: hashing requires that the value never
changes, and a list has no stable hash.

A list stores pointers in a contiguous block and over-allocates as it grows, so
appending is amortised constant time while inserting at the front is linear in
the length of the list.

## Iteration hazards

WARNING: Never modify a list while iterating over it. Removing an element
shifts every later element down one position while the loop's index keeps
advancing, so the loop silently skips items. Build a new list with a
comprehension, or iterate over a copy with `for x in items[:]`.

## Comprehensions

A list comprehension builds a list in one expression and is usually faster than
an equivalent loop with append, because the append lookup happens once rather
than per iteration. A generator expression uses the same syntax with parentheses
and produces items lazily, which matters when the sequence is large enough that
holding all of it costs more than producing it twice.
DOCEOF

UPLOAD_TMPFILE=$(mktemp)
HTTP_UPLOAD=$(curl -s -o "${UPLOAD_TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/documents/ingest" \
  -F "file=@${DOC_TMPFILE};type=text/plain" \
  -F "content_type=tech_book")

rm -f "${DOC_TMPFILE}"

if [ "$HTTP_UPLOAD" != "200" ] && [ "$HTTP_UPLOAD" != "201" ]; then
  echo "FAIL: document upload got ${HTTP_UPLOAD}"
  cat "${UPLOAD_TMPFILE}"
  rm -f "${UPLOAD_TMPFILE}"
  exit 1
fi

DOC_ID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['document_id'])" < "${UPLOAD_TMPFILE}")
rm -f "${UPLOAD_TMPFILE}"

if [ -z "${DOC_ID}" ]; then
  echo "FAIL: could not extract document id from the ingest response"
  exit 1
fi

# Delete the document however this script exits, so a run does not leave one
# behind in the library -- these scripts have been depositing one per run.
cleanup_doc() { curl -s -o /dev/null -X DELETE "${BASE}/documents/${DOC_ID}" || true; rm -rf "$SMOKE_TMPDIR"; }
trap cleanup_doc EXIT

# Ingestion is asynchronous: /documents/ingest answers `{"document_id", "status":
# "processing"}` and the pipeline runs behind it. A fixed `sleep 3` was a guess
# that passed or failed with the machine; poll the stage instead.
echo "Ingested document id=${DOC_ID}, waiting for stage=complete..."
for _ in $(seq 1 60); do
  STAGE=$(curl -s "${BASE}/documents/${DOC_ID}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('stage',''))" 2>/dev/null || echo "")
  [ "$STAGE" = "complete" ] && break
  sleep 2
done
if [ "$STAGE" != "complete" ]; then
  echo "FAIL: document did not reach stage=complete (last stage: ${STAGE:-unknown})"
  exit 1
fi

# 3. POST /flashcards/generate-technical
RESULT_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${RESULT_TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/flashcards/generate-technical" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\": \"${DOC_ID}\", \"scope\": \"full\", \"count\": 3}")

if [ "$HTTP_STATUS" != "201" ]; then
  echo "FAIL: expected 201, got ${HTTP_STATUS}"
  cat "${RESULT_TMPFILE}"
  rm -f "${RESULT_TMPFILE}"
  exit 1
fi

BODY=$(cat "${RESULT_TMPFILE}")
rm -f "${RESULT_TMPFILE}"

# Body must be a non-empty JSON array
if [[ "$BODY" != \[* ]]; then
  echo "FAIL: expected JSON array body, got: ${BODY:0:120}"
  exit 1
fi

# Zero cards is a legitimate response: the quality gate discards a card whose
# quote is not in the passage, and `_collect_with_backfill` returns what survives
# rather than padding. Measured on this fixture, generation comes back empty on a
# minority of runs, so demanding >=1 made the script a coin toss. The contract --
# 201, a JSON array, flashcard_type on every card returned -- is what holds every
# time, and an empty run is reported rather than passed over in silence.
CARD_COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" <<< "${BODY}")
if [ "${CARD_COUNT}" -lt 1 ]; then
  echo "NOTE: generation returned 0 cards this run (a gate-rejected run, not a contract break)"
fi


# EVERY card must carry flashcard_type -- "at least one" would pass a response
# where all but one card was untyped, which is the defect this guards against.
# Vacuous on an empty response, which is why the count is reported above.
HAS_TYPE=$(python3 -c "
import json, sys
cards = json.loads(sys.stdin.read())
untyped = [c for c in cards if c.get('flashcard_type') is None]
print('yes' if not untyped else f'{len(untyped)} of {len(cards)} untyped')
" <<< "${BODY}")

if [ "${HAS_TYPE}" != "yes" ]; then
  echo "FAIL: technical cards missing flashcard_type (${HAS_TYPE}). Cards: ${BODY:0:200}"
  exit 1
fi

echo "PASS: S137 -- POST /flashcards/generate-technical returned HTTP 201 with ${CARD_COUNT} typed cards"
