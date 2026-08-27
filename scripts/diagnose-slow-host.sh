#!/usr/bin/env bash
# One command that answers "why is answering slow on this host".
#
# Written because diagnosing it took six round-trips of relayed commands between
# two machines. Everything needed to tell the causes apart is collected here:
# which build is running, whether the host measured itself slow at start-up,
# which context budget that resolved to, and where a real question's time went.
#
# Read-only. Starts nothing, changes nothing.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=============================================================="
echo " Luminary slow-host diagnostic"
echo "=============================================================="

echo
echo "-- build under test ------------------------------------------"
git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo "  not a git checkout"
git -C "$REPO_ROOT" status --short 2>/dev/null | head -5

echo
echo "-- is a backend reachable ------------------------------------"
BASE=""
for u in "http://localhost:7820" "http://localhost:7820/api" \
         "http://127.0.0.1:7820" "http://127.0.0.1:7820/api"; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$u/health" 2>/dev/null || true)
    echo "  $u/health -> ${code:-000}"
    if [ "$code" = "200" ] && [ -z "$BASE" ]; then BASE="$u"; fi
done

if [ -z "$BASE" ]; then
    echo
    echo "  NO BACKEND REACHABLE. Nothing below can be measured."
    echo "  Start one, wait ~30s for warm-up, and re-run this script:"
    echo "     make luminary       # the way a user runs it"
    echo "     make dev            # backend on :7820 with reload"
    echo
    echo "  NOTE: the bundled Luminary.app runs its OWN backend, not this"
    echo "  checkout. Testing the .app does not test this branch."
    echo "=============================================================="
    exit 1
fi
echo "  using: $BASE"

echo
echo "-- slow-host profile -----------------------------------------"
curl -s -m 30 "$BASE/evals/environment" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("  /evals/environment did not return JSON")
    raise SystemExit
probe = d.get("startup_probe_seconds")
slow  = d.get("local_inference_slow")
rows = [
    ("startup_probe_seconds", probe),
    ("local_inference_slow", slow),
    ("qa_context_token_budget", d.get("qa_context_token_budget")),
    ("budget_reason", d.get("qa_context_budget_reason")),
    ("chat_model", d.get("chat_model")),
    ("generation_model", d.get("generation_model")),
    ("rerank_enabled", d.get("rerank_enabled")),
    ("backend_version", d.get("backend_version")),
    ("library", d.get("library")),
]
for k, v in rows:
    print("  %-24s %s" % (k, v))
print()
if probe is None:
    print("  VERDICT: no start-up probe recorded, so the profile CANNOT engage")
    print("  and this host keeps the full budget. Either warm-up has not")
    print("  finished (wait 30s and re-run) or it failed.")
elif not slow:
    print("  VERDICT: measured %.1fs at start-up, NOT classified slow, so the" % probe)
    print("  full budget is correct for this host.")
else:
    print("  VERDICT: profile ENGAGED (%.1fs probe). Narrow budget in use." % probe)
'

echo
echo "-- ollama ----------------------------------------------------"
curl -s -m 10 "${OLLAMA_URL:-http://localhost:11434}/api/ps" | python3 -c '
import sys, json
try:
    ms = json.load(sys.stdin).get("models", [])
except Exception:
    print("  ollama not reachable")
    raise SystemExit
if not ms:
    print("  no model resident -- the next question pays a load")
for m in ms:
    vram = m.get("size_vram", 0) / 1e9
    tail = "  (CPU-only: size_vram 0)" if vram < 0.1 else ""
    print("  %s  vram=%.1fGB%s" % (m.get("name"), vram, tail))
'

echo
echo "-- one real question (this will take as long as it takes) -----"
curl -s -m 900 -X POST "$BASE/qa" \
     -H 'Content-Type: application/json' \
     -d '{"question":"What is this document about?","include_context":true}' \
     -o /dev/null \
     -w "  time to first byte : %{time_starttransfer}s\n  total              : %{time_total}s\n  http               : %{http_code}\n" \
     2>/dev/null || echo "  question failed"

echo
echo "-- what the answer path logged -------------------------------"
LOGS=""
for f in "$HOME/Library/Logs/Luminary/luminary.log" "$REPO_ROOT/backend/luminary.log"; do
    [ -f "$f" ] && LOGS="$f" && break
done
if [ -n "$LOGS" ]; then
    grep -E "Warmup:|synthesize_node:|classify_node|prompt ~" "$LOGS" 2>/dev/null | tail -12 \
        || echo "  no matching lines in $LOGS"
else
    echo "  no log file found; if running under Docker use:"
    echo "     docker compose logs app | grep -E 'Warmup:|synthesize_node:|prompt ~' | tail -12"
    echo "  if running via 'make dev', the lines are in that terminal."
fi

echo
echo "=============================================================="
echo " Paste everything above."
echo "=============================================================="
