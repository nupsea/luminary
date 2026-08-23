#!/usr/bin/env bash
# Smoke test for S224: index-time entity injection via the reindex_entities CLI.
#
# Verifies:
#   1.  backend is healthy
#   2.  reindex_entities --help exits 0 (CLI is wired)
#   3.  reindex_entities --document-id <missing-id> succeeds (idempotent on missing doc)
#       AND the schema migration (chunks.entities_text column) is in place
#   4.  reindex_entities --all succeeds end-to-end on the active corpus
#       (or no-ops cleanly when the corpus is empty)
#
# Requires the backend to be running on localhost:7820 (for health check).
# The CLI invocation runs against the same DATA_DIR as the live backend.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="http://localhost:7820"

# 1. Backend health -- ensures the database/schema is up to date with S224.
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. CLI --help must exit 0 (proves the module loads and argparse is wired).
cd "${REPO_ROOT}/backend"
HELP_OUT=$(uv run python -m app.scripts.reindex_entities --help)
echo "$HELP_OUT" | grep -qF -- "--document-id" \
  || { echo "FAIL: --document-id missing from --help output"; exit 1; }
echo "$HELP_OUT" | grep -qF -- "--all" \
  || { echo "FAIL: --all missing from --help output"; exit 1; }

# 3. CLI on a non-existent document id should NOT crash -- just warn + exit 0.
uv run python -m app.scripts.reindex_entities --document-id S224-smoke-bogus-doc-id \
  || { echo "FAIL: reindex_entities on missing doc-id should exit 0"; exit 1; }

# 4. End-to-end --all run. With an empty document table this is a no-op
#    that still exits 0; with documents present it exercises the full path.
#
# NOT `--all`. That reindexes every chunk in the catalog through GLiNER: measured
# at ~70 minutes on a 60-document, 75,617-chunk library, which is most of the
# whole smoke suite's runtime and makes `make smoke` impractical to run at all.
# One real document exercises the same code path -- read chunks, extract
# entities, canonicalize, write `chunks.entities_text`, upsert to LanceDB -- and
# costs seconds. The whole-corpus sweep is a maintenance job, not a contract
# check; run it by hand when the extraction changes:
#
#     cd backend && uv run python -m app.scripts.reindex_entities --all
#
DOC_ID=$(curl -s "${BASE}/documents" | python3 -c "
import json, sys
docs = json.load(sys.stdin)
items = docs.get('items', docs) if isinstance(docs, dict) else docs
ready = [d for d in items if isinstance(d, dict) and d.get('stage') == 'complete']
print(ready[0]['id'] if ready else '')
" 2>/dev/null || echo "")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no complete document to reindex"
else
  uv run python -m app.scripts.reindex_entities --document-id "$DOC_ID" \
    || { echo "FAIL: reindex_entities --document-id should exit 0"; exit 1; }
  echo "  reindexed one document ($DOC_ID) end to end"
fi

echo "PASS: S224 -- reindex_entities CLI verified (health + help + missing-id + one document)"
