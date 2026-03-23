#!/usr/bin/env bash
# Smoke test for S86 -- entity disambiguation
# Ingests a small TXT file with known entity variants, waits for completion,
# then asserts GET /graph/{doc_id} returns at least 1 entity node.
set -euo pipefail

BASE="http://localhost:7820"
FIXTURE="/tmp/s86_smoke_fixture.txt"

# Create a minimal fixture with known entity variants
cat > "$FIXTURE" <<'FIXTURE_EOF'
The Adventures of Sherlock Holmes

Chapter 1: The Case of the Missing Clue

Mr. Holmes arrived at Baker Street early in the morning.
Sherlock Holmes examined the evidence carefully.
Holmes concluded that the crime occurred at midnight.
Dr. Watson recorded Holmes observations in his journal.
Watson and Mr. Holmes then departed for Scotland Yard.
FIXTURE_EOF

echo "S86 smoke: uploading fixture document"
UPLOAD=$(curl -sf -X POST "$BASE/ingest" \
  -F "file=@$FIXTURE;type=text/plain" \
  -F "content_type=book")
DOC_ID=$(echo "$UPLOAD" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
echo "S86 smoke: document_id=$DOC_ID"

echo "S86 smoke: waiting for ingestion to complete (max 120s)"
STAGE=""
for i in $(seq 1 24); do
  STAGE=$(curl -sf "$BASE/documents/$DOC_ID" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stage',''))")
  echo "  stage=$STAGE (attempt $i)"
  if [ "$STAGE" = "complete" ]; then break; fi
  if [ "$STAGE" = "error" ]; then echo "FAIL: ingestion stage=error"; rm -f "$FIXTURE"; exit 1; fi
  sleep 5
done

if [ "$STAGE" != "complete" ]; then
  echo "FAIL: ingestion did not complete within 120s (stage=$STAGE)"
  rm -f "$FIXTURE"
  exit 1
fi

echo "S86 smoke: GET /graph/$DOC_ID"
GRAPH=$(curl -sf "$BASE/graph/$DOC_ID")
NODES=$(echo "$GRAPH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('nodes',[])))")
echo "S86 smoke: node count=$NODES"
if [ "$NODES" -lt 1 ]; then
  echo "FAIL: expected at least 1 entity node, got $NODES"
  rm -f "$FIXTURE"
  exit 1
fi

echo "S86 smoke: all checks passed (nodes=$NODES)"
rm -f "$FIXTURE"
