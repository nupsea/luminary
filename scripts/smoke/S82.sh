#!/usr/bin/env bash
# Smoke test for S82: executive summary synthesises themes, not per-passage lists.
# Verifies that Gutenberg/distribution metadata does not appear in the output.
set -euo pipefail

BASE="${BACKEND_URL:-http://localhost:8000}"

# Ingest a minimal document that contains Gutenberg boilerplate mixed with content
INGEST_RESP=$(curl -sf -X POST "$BASE/documents/ingest" \
  -F "file=@/dev/stdin;filename=smoke_s82.txt;type=text/plain" \
  -F "content_type=book" <<- 'EOF'
Chapter 1: The Adventure Begins

Sherlock Holmes sat in his armchair, fingers steepled beneath his chin,
deep in thought about the curious case of the missing coronet.

Chapter 2: The Investigation

Holmes examined every corner of the room with his magnifying glass,
noting the faint impressions left by muddy boots near the fireplace.

Chapter 3: The Resolution

The case was solved through careful deduction. The culprit was caught
red-handed, and justice was served swiftly.

Project Gutenberg License Notice

This eBook is for the use of anyone anywhere in the United States.
Terms of Use: distribution, reproduction, and electronic work are
subject to the Archive Foundation agreement.
EOF
)

DOC_ID=$(echo "$INGEST_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
echo "Created document: $DOC_ID"

# Wait briefly for ingestion background tasks
sleep 2

# Request executive summary with force_refresh=true and collect streaming output
SUMMARY_TEXT=$(curl -sf \
  "$BASE/summarize/$DOC_ID?mode=executive&force_refresh=true" \
  --header "Accept: text/event-stream" \
  | grep '^data:' \
  | python3 -c "
import sys, json
tokens = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'):
        continue
    payload = json.loads(line[5:].strip())
    if 'token' in payload:
        tokens.append(payload['token'])
print(''.join(tokens))
")

echo "Summary text: $SUMMARY_TEXT"

# Assert HTTP 200 was received (curl -sf already handles this — non-2xx exits with error)

# Assert the output does NOT contain Gutenberg or distribution metadata
python3 -c "
import sys
text = '''$SUMMARY_TEXT'''.lower()
forbidden = ['project gutenberg', 'distribution']
for word in forbidden:
    assert word not in text, f'FAIL: executive summary contains forbidden metadata: {word!r}'
print('PASS: executive summary contains no Gutenberg/distribution metadata')
"

echo "S82 smoke test PASSED"
