#!/usr/bin/env bash
# Smoke test for S83: confidence fixes and multi-doc scope improvements.
# 1. POST /qa with scope='all' factual query — asserts HTTP 200, confidence != 'low'
# 2. POST /qa with scope='all' summary query — asserts HTTP 200, non-empty answer
set -euo pipefail

BASE="${BACKEND_URL:-http://localhost:7820}"

# ---- Ingest two small documents so scope='all' retrieval has content ----
DOC1=$(curl -sf -X POST "$BASE/documents/ingest" \
  -F "file=@/dev/stdin;filename=smoke_s83_a.txt;type=text/plain" \
  -F "content_type=book" <<< \
  "Sherlock Holmes examined the room carefully. The mystery deepened each moment." \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")

DOC2=$(curl -sf -X POST "$BASE/documents/ingest" \
  -F "file=@/dev/stdin;filename=smoke_s83_b.txt;type=text/plain" \
  -F "content_type=book" <<< \
  "Watson recorded the events in his journal. The adventure concluded successfully." \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")

echo "Ingested doc1=$DOC1 doc2=$DOC2"
sleep 2

# ---- (1) Factual query across all docs — confidence should not be 'low' ----
QA_RESP=$(curl -sf -X POST "$BASE/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "Who is the main character?", "scope": "all"}' \
  --header "Accept: text/event-stream" \
  | grep '^data:' \
  | python3 -c "
import sys, json
events = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'):
        continue
    payload = json.loads(line[5:].strip())
    events.append(payload)
# Find the done event
done = next((e for e in events if e.get('done')), None)
if done:
    print(json.dumps(done))
else:
    print(json.dumps({'confidence': 'unknown'}))
")

echo "QA response (factual): $QA_RESP"
python3 -c "
import sys, json
resp = json.loads('$QA_RESP')
conf = resp.get('confidence', 'unknown')
assert conf != 'low', f'FAIL: factual query returned low confidence: {conf}'
print(f'PASS: factual query confidence={conf} (not low)')
"

# ---- (2) Summary query — answer should be non-empty ----
SUM_RESP=$(curl -sf -X POST "$BASE/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarize all documents", "scope": "all"}' \
  --header "Accept: text/event-stream" \
  | grep '^data:' \
  | python3 -c "
import sys, json
tokens = []
done = None
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'):
        continue
    payload = json.loads(line[5:].strip())
    if 'token' in payload:
        tokens.append(payload['token'])
    if payload.get('done'):
        done = payload
full = ''.join(tokens)
print(json.dumps({'answer': full, 'confidence': done.get('confidence') if done else 'unknown'}))
")

echo "Summary response: $SUM_RESP"
python3 -c "
import sys, json
resp = json.loads('$SUM_RESP')
answer = resp.get('answer', '')
assert len(answer) > 0, f'FAIL: summary answer is empty'
print(f'PASS: summary answer is non-empty ({len(answer)} chars)')
"

echo "S83 smoke test PASSED"
