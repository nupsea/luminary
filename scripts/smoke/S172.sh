#!/usr/bin/env bash
# Smoke test for S172: Note nodes in Viz Knowledge graph
# Tests GET /graph/{doc_id}?include_notes=true/false and GET /graph?include_notes=true

set -euo pipefail

BASE="http://localhost:8000"

echo "=== S172 Smoke Test: Note nodes in Viz graph ==="

# 1. GET /graph?doc_ids=&include_notes=false (baseline -- no notes)
echo "1. GET /graph?doc_ids=&include_notes=false"
RESP=$(curl -s -w "\n%{http_code}" "$BASE/graph?doc_ids=&include_notes=false")
CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)

if [ "$CODE" != "200" ]; then
  echo "FAIL: Expected 200, got $CODE"
  echo "Body: $BODY"
  exit 1
fi

echo "$BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'nodes' in data, 'missing nodes key'
assert 'edges' in data, 'missing edges key'
note_nodes=[n for n in data['nodes'] if n.get('type')=='note']
assert len(note_nodes)==0, f'expected 0 note nodes with include_notes=false, got {len(note_nodes)}'
print('  OK: no note nodes when include_notes=false, nodes/edges keys present')
"

# 2. GET /graph?doc_ids=&include_notes=true (library-wide, supports param)
echo "2. GET /graph?doc_ids=&include_notes=true"
RESP2=$(curl -s -w "\n%{http_code}" "$BASE/graph?doc_ids=&include_notes=true")
CODE2=$(echo "$RESP2" | tail -1)
BODY2=$(echo "$RESP2" | head -1)

if [ "$CODE2" != "200" ]; then
  echo "FAIL: Expected 200, got $CODE2"
  echo "Body: $BODY2"
  exit 1
fi

echo "$BODY2" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'nodes' in data, 'missing nodes key'
assert 'edges' in data, 'missing edges key'
print('  OK: include_notes=true on library endpoint returns 200 with nodes/edges')
"

# 3. Get a document, test document-scoped endpoints
echo "3. Checking document graph endpoints"
DOCS_RESP=$(curl -s "$BASE/documents?page=1&page_size=5&sort=newest")
DOC_ID=$(echo "$DOCS_RESP" | python3 -c "
import sys,json
data=json.load(sys.stdin)
items=data.get('items',[])
if items:
    print(items[0]['id'])
else:
    print('')
" 2>/dev/null || echo "")

if [ -n "$DOC_ID" ]; then
  echo "3a. GET /graph/$DOC_ID?include_notes=false"
  D_RESP=$(curl -s -w "\n%{http_code}" "$BASE/graph/$DOC_ID?include_notes=false")
  D_CODE=$(echo "$D_RESP" | tail -1)
  D_BODY=$(echo "$D_RESP" | head -1)

  if [ "$D_CODE" != "200" ]; then
    echo "FAIL: Expected 200, got $D_CODE"
    echo "Body: $D_BODY"
    exit 1
  fi

  echo "$D_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'nodes' in data, 'missing nodes key'
note_nodes=[n for n in data['nodes'] if n.get('type')=='note']
assert len(note_nodes)==0, f'expected 0 note nodes with include_notes=false, got {len(note_nodes)}'
print('  OK: no note nodes in document graph with include_notes=false')
"

  echo "3b. GET /graph/$DOC_ID?include_notes=true (may return 0 note nodes if none ingested)"
  DN_RESP=$(curl -s -w "\n%{http_code}" "$BASE/graph/$DOC_ID?include_notes=true")
  DN_CODE=$(echo "$DN_RESP" | tail -1)
  DN_BODY=$(echo "$DN_RESP" | head -1)

  if [ "$DN_CODE" != "200" ]; then
    echo "FAIL: Expected 200, got $DN_CODE"
    echo "Body: $DN_BODY"
    exit 1
  fi

  echo "$DN_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'nodes' in data, 'missing nodes key'
assert 'edges' in data, 'missing edges key'
note_nodes=[n for n in data['nodes'] if n.get('type')=='note']
# If any note nodes are present, validate their structure
for n in note_nodes:
    assert n.get('type') == 'note', f'wrong type: {n.get(\"type\")}'
    assert 'note_id' in n, f'missing note_id field on note node'
    assert 'label' in n, f'missing label field on note node'
    assert 'id' in n, f'missing id field on note node'
if note_nodes:
    print(f'  OK: {len(note_nodes)} note node(s) found with correct structure (id, note_id, label, type)')
else:
    print('  OK: 0 note nodes (none with entity edges in this document -- valid empty state)')
"
else
  echo "3. No documents found -- skipping document-scoped tests (OK for fresh install)"
fi

# 4. Test note node structure by creating a note and verifying graph endpoint stability
echo "4. Create note and verify include_notes=true endpoint remains stable"
NOTE_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"content": "S172 smoke test note: backpropagation gradient descent neural network.", "tags": ["ml"]}' \
  "$BASE/notes")
NOTE_CODE=$(echo "$NOTE_RESP" | tail -1)
NOTE_BODY=$(echo "$NOTE_RESP" | head -1)

if [ "$NOTE_CODE" != "201" ]; then
  echo "FAIL: Expected 201 creating note, got $NOTE_CODE"
  echo "Body: $NOTE_BODY"
  exit 1
fi

NOTE_ID=$(echo "$NOTE_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  OK: created note id=$NOTE_ID"

# After note creation, include_notes=true must still return 200 and valid structure
AFTER_RESP=$(curl -s -w "\n%{http_code}" "$BASE/graph?doc_ids=&include_notes=true")
AFTER_CODE=$(echo "$AFTER_RESP" | tail -1)
AFTER_BODY=$(echo "$AFTER_RESP" | head -1)

if [ "$AFTER_CODE" != "200" ]; then
  echo "FAIL: Expected 200 after note creation, got $AFTER_CODE"
  exit 1
fi

echo "$AFTER_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'nodes' in data, 'missing nodes key after note creation'
assert 'edges' in data, 'missing edges key after note creation'
note_nodes=[n for n in data['nodes'] if n.get('type')=='note']
print(f'  OK: include_notes=true stable after note creation; {len(note_nodes)} note node(s) in graph')
"

# 5. Verify include_notes=false on doc endpoint never returns note nodes
if [ -n "$DOC_ID" ]; then
  echo "5. include_notes defaults to false (no ?include_notes param)"
  DEFAULT_RESP=$(curl -s -w "\n%{http_code}" "$BASE/graph/$DOC_ID")
  DEFAULT_CODE=$(echo "$DEFAULT_RESP" | tail -1)
  DEFAULT_BODY=$(echo "$DEFAULT_RESP" | head -1)

  if [ "$DEFAULT_CODE" != "200" ]; then
    echo "FAIL: Expected 200 for default graph, got $DEFAULT_CODE"
    exit 1
  fi

  echo "$DEFAULT_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
note_nodes=[n for n in data['nodes'] if n.get('type')=='note']
assert len(note_nodes)==0, f'expected 0 note nodes by default, got {len(note_nodes)}'
print('  OK: default graph (no include_notes param) returns 0 note nodes')
"
fi

echo ""
echo "=== S172 Smoke Test PASSED ==="
