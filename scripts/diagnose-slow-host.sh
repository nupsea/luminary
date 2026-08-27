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
# Probed with /settings, NOT /health. In public mode (which is what the Docker
# image runs) the API lives under /api, but /health is deliberately registered at
# BOTH the root and the prefix for container probes -- so a /health check picks
# the root, and every real call after it then falls through to the SPA. That is
# a 200 with an HTML body on GET and a 405 on `POST /qa`, which is how this
# script previously reported "question failed" against a perfectly healthy
# backend. The settings router is registered in every mode, so a JSON
# content-type from it is what actually identifies the API base.
BASE=""
for u in "http://localhost:7820" "http://localhost:7820/api" \
         "http://127.0.0.1:7820" "http://127.0.0.1:7820/api"; do
    ct=$(curl -s -o /dev/null -w "%{http_code} %{content_type}" -m 5 "$u/settings" 2>/dev/null || true)
    echo "  $u/settings -> ${ct:-000}"
    case "$ct" in
        200\ application/json*) [ -z "$BASE" ] && BASE="$u" ;;
    esac
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

# Where this backend's own lines can be read from. Under Docker there is no log
# file on this side of the VM, so `docker logs` is the only source -- and it is
# also the only source for the slow-host profile there, because
# /evals/environment belongs to the `full`-mode quality dashboard
# (surface-manifest.json) while the container runs LUMINARY_MODE=public.
LOG_FILE=""
for f in "$HOME/Library/Logs/Luminary/luminary.log" "$REPO_ROOT/backend/luminary.log"; do
    [ -f "$f" ] && LOG_FILE="$f" && break
done
DOCKER_APP=$(docker ps --filter "label=com.docker.compose.service=app" \
                       --format '{{.Names}}' 2>/dev/null | head -1)

app_logs() {
    if [ -n "$DOCKER_APP" ]; then
        docker logs "$DOCKER_APP" 2>&1
    elif [ -n "$LOG_FILE" ]; then
        cat "$LOG_FILE"
    fi
}

if [ -n "$DOCKER_APP" ]; then
    echo "  logs:  docker container $DOCKER_APP"
elif [ -n "$LOG_FILE" ]; then
    echo "  logs:  $LOG_FILE"
else
    echo "  logs:  none found -- the log-derived lines below will be empty"
fi

echo
echo "-- slow-host profile -----------------------------------------"
ENV_JSON=$(mktemp)
ENV_CODE=$(curl -s -m 30 -o "$ENV_JSON" -w "%{http_code}" "$BASE/evals/environment" 2>/dev/null || true)
if [ "$ENV_CODE" = "200" ]; then
    python3 -c '
import sys, json
try:
    d = json.load(open(sys.argv[1]))
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
' "$ENV_JSON"
else
    # Not an error and not a fallback for a broken backend: /evals/environment is
    # a `full`-mode surface, and the Docker image runs public mode, so under
    # Docker this endpoint is 404 by design. The same two facts are in the log --
    # the keep-warm decision line prints the probe and states which way the gate
    # went -- so the diagnostic reports them from there rather than reporting
    # nothing on the one topology this branch exists to measure.
    echo "  /evals/environment -> $ENV_CODE (full-mode surface; public mode does not mount it)"
    echo "  reading the same facts from the log instead:"
    app_logs | grep -E "Keep-warm (on|off):" | tail -2 | sed 's/^/    /'
    app_logs | grep -E "Keep-warm (on|off):" | tail -1 | python3 -c '
import sys, re
line = sys.stdin.read()
if not line.strip():
    print()
    print("  VERDICT: no keep-warm line in the log yet. Warm-up has not reached")
    print("  the probe (wait ~30s and re-run), or the log source is wrong.")
    raise SystemExit
m = re.search(r"took ([0-9.]+)s at start-up", line)
print()
if "Keep-warm off" in line and m is None:
    print("  VERDICT: probe UNMEASURED, so the profile CANNOT engage and this")
    print("  host keeps the full budget. Ollama was likely down at start-up.")
elif "Keep-warm off" in line:
    print("  VERDICT: measured %ss at start-up, NOT classified slow, so the" % m.group(1))
    print("  full budget is correct for this host.")
else:
    print("  VERDICT: profile ENGAGED (%ss probe). Narrow budget in use." % m.group(1))
print("  The resolved budget itself is not logged until a question is answered;")
print("  it is on the synthesize_node line at the bottom of this report.")
'
fi
rm -f "$ENV_JSON"

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
# `total` is the number that matters. curl's time_starttransfer is NOT the
# model's first token here: /qa streams, so the headers come back in ~0.02s
# whatever the model is doing, and reading that as a latency win would be
# reading the HTTP layer. The real one is `LLM time-to-first-token` in the log
# lines below -- 0.019s of headers sat in front of a 30.21s first token on the
# run this note was written from.
curl -s -m 900 -X POST "$BASE/qa" \
     -H 'Content-Type: application/json' \
     -d '{"question":"What is this document about?","include_context":true}' \
     -o /dev/null \
     -w "  response headers in : %{time_starttransfer}s\n  total               : %{time_total}s\n  http                : %{http_code}\n" \
     2>/dev/null || echo "  question failed"

echo
echo "-- what the answer path logged -------------------------------"
# `synthesize_node:` carries the budget that was actually used and how many
# passages survived it, which is the line that says what the narrow budget cost.
if [ -z "$DOCKER_APP" ] && [ -z "$LOG_FILE" ]; then
    echo "  no log source found. Under 'make dev' the lines are in that terminal;"
    echo "  under Docker, start the app with 'make docker-run-host-ollama' so this"
    echo "  script can find the container."
else
    matched=$(app_logs | grep -E "Warmup:|synthesize_node:|classify_node|prompt ~|\[perf\]" | tail -16)
    if [ -n "$matched" ]; then
        echo "$matched" | sed 's/^/  /'
    else
        echo "  no matching lines in the log source above"
    fi
fi

echo
echo "=============================================================="
echo " Paste everything above."
echo "=============================================================="
