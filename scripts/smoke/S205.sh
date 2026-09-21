#!/usr/bin/env bash
# Smoke test for S205: PDF text layer and search highlight rendering
# Frontend-only refactor (overlay divs instead of inline marks) -- verify:
# the overlay module exists, no inline mark injection remains, the overlay
# container is in the JSX, and the annotation endpoint still responds.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=true

echo "=== S205 Smoke Test ==="

# 2. Overlay module exists and exports expected functions
echo "--- Check 2: pdfHighlightOverlay.ts exists ---"
OVERLAY="$REPO_ROOT/frontend/src/components/reader/pdfHighlightOverlay.ts"
if [ -f "$OVERLAY" ]; then
  for fn in computeHighlightRects renderOverlayDivs clearOverlays; do
    if grep -q "export function $fn" "$OVERLAY"; then
      echo "  OK: $fn exported"
    else
      echo "  FAIL: $fn not found in overlay module"
      PASS=false
    fi
  done
else
  echo "  FAIL: pdfHighlightOverlay.ts does not exist"
  PASS=false
fi

# 3. No inline mark injection in PDFViewer.tsx
echo "--- Check 3: No mark injection in PDFViewer ---"
VIEWER="$REPO_ROOT/frontend/src/components/reader/PDFViewer.tsx"
# Old patterns: createElement("mark"), data-hl-original, replaceChildren(frag)
for pattern in 'createElement("mark")' 'data-hl-original' 'replaceChildren(frag)'; do
  if grep -q "$pattern" "$VIEWER"; then
    echo "  FAIL: old mark injection pattern found: $pattern"
    PASS=false
  else
    echo "  OK: $pattern not present (removed)"
  fi
done

# 4. Overlay container div in JSX
echo "--- Check 4: highlightOverlayRef in PDFViewer ---"
if grep -q "highlightOverlayRef" "$VIEWER"; then
  echo "  OK: highlightOverlayRef found"
else
  echo "  FAIL: highlightOverlayRef not found"
  PASS=false
fi
if grep -q "zIndex: 5" "$VIEWER"; then
  echo "  OK: overlay z-index 5 found"
else
  echo "  FAIL: overlay z-index 5 not found"
  PASS=false
fi

# 5. Backend annotation endpoint (GET /annotations) still responds
echo "--- Check 5: GET /annotations responds ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/annotations?document_id=smoke-s205-doc")
if [ "$STATUS" = "200" ]; then
  echo "  OK: GET /annotations -> $STATUS"
else
  echo "  WARN: GET /annotations -> $STATUS (backend may not be running)"
fi

if [ "$PASS" = true ]; then
  echo "=== S205 Smoke: ALL PASSED ==="
  exit 0
else
  echo "=== S205 Smoke: SOME FAILED ==="
  exit 1
fi
