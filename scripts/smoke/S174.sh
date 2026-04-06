#!/usr/bin/env bash
# Smoke test for S174 -- Export collections as Obsidian Markdown vault and Anki deck
set -euo pipefail

BASE="http://localhost:8000"

echo "=== S174 smoke: Export collection endpoints ==="

# Create a test collection
COL=$(curl -sf -X POST "${BASE}/collections" \
  -H "Content-Type: application/json" \
  -d '{"name":"S174 Smoke Collection","color":"#6366F1"}')
COL_ID=$(echo "$COL" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "Created collection: $COL_ID"

# Export as markdown -- check status 200 and Content-Type
MD_RESP=$(curl -sf -w "\n%{http_code}\n%{content_type}" -o /tmp/s174_vault.zip \
  "${BASE}/collections/${COL_ID}/export?format=markdown")
HTTP_CODE=$(echo "$MD_RESP" | tail -2 | head -1)
CTYPE=$(echo "$MD_RESP" | tail -1)
if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: markdown export returned HTTP $HTTP_CODE"
  exit 1
fi
echo "markdown export HTTP 200 OK, content-type=$CTYPE"

# Verify zip is valid (even if empty)
python3 -c "
import zipfile, sys
zf = zipfile.ZipFile('/tmp/s174_vault.zip')
names = zf.namelist()
print(f'  markdown zip valid: {len(names)} files')
"

# Export as anki -- check status 200 and that result is a valid zip (apkg is a zip)
ANKI_RESP=$(curl -sf -w "\n%{http_code}" -o /tmp/s174_deck.apkg \
  "${BASE}/collections/${COL_ID}/export?format=anki")
ANKI_CODE=$(echo "$ANKI_RESP" | tail -1)
if [ "$ANKI_CODE" != "200" ]; then
  echo "FAIL: anki export returned HTTP $ANKI_CODE"
  exit 1
fi
python3 -c "
import zipfile
zf = zipfile.ZipFile('/tmp/s174_deck.apkg')
print(f'  anki apkg valid zip: {len(zf.namelist())} entries')
"
echo "anki export HTTP 200 OK"

# Verify invalid format returns 422
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/collections/${COL_ID}/export?format=csv")
if [ "$STATUS" != "422" ]; then
  echo "FAIL: invalid format returned $STATUS, expected 422"
  exit 1
fi
echo "invalid format returns 422 OK"

# Cleanup
curl -sf -X DELETE "${BASE}/collections/${COL_ID}" || true

echo "=== S174 smoke PASSED ==="
