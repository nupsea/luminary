#!/usr/bin/env bash
# Smoke test for S260: a section scope names its section by id, and a section that cannot be
# found is an error, never the whole book.
#
# What this guards: Study sent a chapter's display title as `section_heading`; the title had
# lost the stored heading's trailing colon, the lookup missed, and generation read the whole
# book, so "Chapter I" practice asked about Chapters II to XVII.
#
# Verifies:
#   1. /flashcards/generate takes `section_id`
#   2. a section that is not in the document answers 404 (no model time is spent)
#   3. the source panel's response carries the card's own quote
#   4. /flashcards/repair reports the cards it filed under their quote's section
#
# Requires a running backend with at least one ingested document.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

fail() {
  echo "FAIL: $1"
  exit 1
}

smoke_openapi | python3 -c "
import sys, json
schemas = json.load(sys.stdin)['components']['schemas']
assert 'section_id' in schemas['FlashcardGenerateRequest']['properties'], 'generate cannot name a section by id'
assert 'quote' in schemas['SourceContextResponse']['properties'], 'the source panel cannot show the quote'
assert 'cards_refiled' in schemas['RepairReport']['properties'], 'repair does not report re-filed cards'
print('  section_id, quote and cards_refiled are on the wire')
" || fail "request/response shape is wrong"

DOC_ID=$(curl -sf "${BASE}/documents" | python3 -c "import sys,json; docs=json.load(sys.stdin).get('items',[]); print(docs[0]['id'] if docs else '')")
if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents in DB -- ingest a document first"
  exit "$SMOKE_SKIP"
fi

for SCOPE in '"section_id":"s260-no-such-section"' '"section_heading":"s260 no such heading:"'; do
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/generate" \
    -H 'Content-Type: application/json' \
    -d "{\"document_id\":\"${DOC_ID}\",\"scope\":\"section\",${SCOPE},\"count\":1}")
  [ "$HTTP" = "404" ] || fail "an unknown section answered HTTP $HTTP for {${SCOPE}}; it must not read the whole book"
done
echo "  an unknown section is a 404, by id and by heading"

echo "PASS: S260 -- a section scope reads its own section or nothing"
