#!/usr/bin/env bash
# Smoke test for S228: GET /evals/environment -- the provenance an eval run records.
#
# Verifies:
#   1. backend is healthy
#   2. GET /evals/environment -- 200 with every field the eval runner stores
#   3. the corpus fingerprint is present and numeric
#   4. models are RESOLVED, not configured: chat_model must not be blank, and in
#      `private` mode it must be the local model rather than a cloud id
#   5. embedding_dim matches the width the stored vectors carry (I-9)

set -euo pipefail

BASE="http://localhost:7820"

fail() {
  echo "FAIL: $1"
  exit 1
}

# 1. Health check
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (got ${HTTP})"

# 2-5. One fetch, all assertions
BODY=$(curl -s -w "\n%{http_code}" "${BASE}/evals/environment")
HTTP=$(echo "$BODY" | tail -1)
CONTENT=$(echo "$BODY" | head -1)
[ "$HTTP" = "200" ] || fail "GET /evals/environment expected 200, got ${HTTP}"

echo "$CONTENT" | python3 -c "
import sys, json
d = json.load(sys.stdin)

required = [
    'backend_version', 'embedding_model', 'embedding_dim', 'chunk_vector_table',
    'rerank_model', 'rerank_depth', 'query_spell_correct', 'llm_mode',
    'chat_model', 'background_model', 'local_chat_model', 'generation_model',
    'vision_model', 'library',
]
missing = [k for k in required if k not in d]
assert not missing, f'missing fields: {missing}'

lib = d['library']
assert isinstance(lib.get('documents'), int), 'library.documents not an int'
assert isinstance(lib.get('chunks'), int), 'library.chunks not an int'

assert d['chat_model'], 'chat_model is blank -- a run would record no model'
if d['llm_mode'] == 'private':
    assert d['chat_model'] == d['local_chat_model'], (
        f\"private mode must resolve to the local model, got {d['chat_model']}\"
    )

assert d['embedding_dim'] == 384, f\"embedding_dim {d['embedding_dim']} != stored vector width\"

print(f\"  build {d['backend_version']}  corpus {lib['documents']} docs / {lib['chunks']} chunks\")
print(f\"  chat {d['chat_model']}  background {d['background_model']}\")
" || fail "GET /evals/environment response did not carry usable provenance"

echo "PASS: S228 -- /evals/environment reports resolved models and corpus fingerprint"
