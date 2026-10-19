#!/usr/bin/env bash
# Ingest the eval corpus into an empty library, then measure it.
#
# `make eval`, `make eval-gen` and `make eval-flashcards` score the dev library as it was
# ingested, so an ingestion change (parsing, chunking, sections) never reaches them. This
# runs the current code end to end on a throwaway library.
#
# Usage: eval_full.sh retrieval|generation|cards|all
# Env:   EVAL_PORT (7850); EVAL_CHAT_MODEL, the model the library answers and writes cards
#        with, pinned before ingestion (a fresh library would use the router default);
#        EVAL_TEXT_MODEL, the judge, for generation and cards;
#        EVAL_BACKEND (a backend checkout to measure instead of this one, e.g. a release
#        worktree: an A/B runs one harness against two builds);
#        KEEP=1 keeps the library; EVAL_FULL_STATE holds history across runs.
set -uo pipefail

SUITE=${1:-retrieval}
REPO=$(cd "$(dirname "$0")/.." && pwd)
# DATA/ and the models are not in git, so a worktree takes them from the main checkout.
MAIN=$(cd "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
BACKEND_DIR=${EVAL_BACKEND:-$REPO/backend}
PORT=${EVAL_PORT:-7850}
URL="http://localhost:$PORT"
STATE=${EVAL_FULL_STATE:-$REPO/.luminary-eval}
RETRIEVAL=(book paper legal play study)
GENERATION=(book paper)
CARDS=flashcards_corpus

case "$SUITE" in
  retrieval | cards | all) DATASETS=("${RETRIEVAL[@]}") ;;
  generation) DATASETS=("${GENERATION[@]}") ;;
  *) echo "usage: $0 retrieval|generation|cards|all" >&2; exit 2 ;;
esac
if [ "$SUITE" != retrieval ] && { [ -z "${EVAL_TEXT_MODEL:-}" ] || [ -z "${EVAL_CHAT_MODEL:-}" ]; }; then
  echo "$SUITE needs EVAL_TEXT_MODEL (the judge) and EVAL_CHAT_MODEL (the model measured)" >&2
  exit 2
fi
if curl -s -m2 -o /dev/null "$URL/health"; then
  echo "Port $PORT is in use; set EVAL_PORT" >&2; exit 2
fi

LIB=$(mktemp -d "${TMPDIR:-/tmp}/luminary-eval-full.XXXXXX")
if [ -d "$MAIN/.luminary/models" ]; then
  mkdir -p "$LIB/models"
  for m in "$MAIN/.luminary/models"/*; do ln -s "$m" "$LIB/models/"; done
fi

(cd "$BACKEND_DIR" && DATA_DIR="$LIB" exec uv run uvicorn app.main:app --port "$PORT") \
  > "$LIB/backend.log" 2>&1 &
BACKEND=$!
cleanup() {
  kill "$BACKEND" 2>/dev/null
  wait "$BACKEND" 2>/dev/null
  if [ "${KEEP:-}" = 1 ]; then echo "Library kept at $LIB"; else rm -rf "$LIB"; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

for _ in $(seq 120); do
  curl -s -m2 -o /dev/null "$URL/health" && break
  kill -0 "$BACKEND" 2>/dev/null || { tail -20 "$LIB/backend.log"; exit 1; }
  sleep 2
done
curl -s -m2 -o /dev/null "$URL/health" || { echo "Backend did not come up" >&2; exit 1; }

# Pinned before ingestion: ingestion writes the first chapters' cards with this model.
if [ -n "${EVAL_CHAT_MODEL:-}" ]; then
  curl -s -m30 -X PATCH "$URL/settings/llm" -H 'Content-Type: application/json' \
    -d "{\"mode\":\"private\",\"local_chat_model\":\"$EVAL_CHAT_MODEL\"}" > /dev/null
fi
ACTIVE=$(curl -s -m30 "$URL/settings/llm" | jq -r '.active_model // empty')
if [ -n "${EVAL_CHAT_MODEL:-}" ] && [ "$ACTIVE" != "$EVAL_CHAT_MODEL" ]; then
  echo "Active model is '$ACTIVE', not $EVAL_CHAT_MODEL" >&2; exit 1
fi
echo "Library $LIB, active model: $ACTIVE"

# The manifest maps sources to the last library's ids, which no longer exist.
mkdir -p "$STATE"
rm -f "$STATE/manifest.json"
export LUMINARY_EVAL_STATE_DIR="$STATE" LUMINARY_EVAL_SOURCE_ROOT="$MAIN" PYTHONUNBUFFERED=1
cd "$REPO/evals"
run() { UV_CACHE_DIR="$REPO/.uv-cache" uv run --no-sync python run_eval.py --backend-url "$URL" "$@"; }

# The whole corpus goes in before anything is scored: retrieval scores move with
# what else the library holds, so every dataset must see the same library.
for d in "${DATASETS[@]}"; do
  run --dataset "$d" --ingest-only || { echo "Ingesting $d failed" >&2; exit 1; }
done
# The ingest helper may move on at a stage that has stalled; scoring may not, since the
# keyword index lands last and a half-indexed document scores low without saying so.
for _ in $(seq 180); do
  pending=$(curl -s -m10 "$URL/documents?page_size=100" | jq '[.items[] | select(.stage != "complete")] | length')
  [ "$pending" = 0 ] && break
  sleep 10
done
[ "$pending" = 0 ] || { echo "$pending documents never reached complete" >&2; exit 1; }

# Enrichment (chapter cards, web refs, concept links) runs after "complete", and every job
# calls the model. Anything that measures a model waits it out: the repair and delivery
# counters a run reads are process-wide, so a background card would count as a measured one.
# On five books that is hours; EVAL_ENRICH_WAIT_MIN bounds it.
if [ "$SUITE" != retrieval ]; then
  deadline=$(( $(date +%s) + ${EVAL_ENRICH_WAIT_MIN:-240} * 60 ))
  next_report=0
  while :; do
    queue=$(curl -s -m10 "$URL/enrichment/queue")
    [ "$(jq -r .active <<<"$queue" 2>/dev/null)" = false ] && break
    now=$(date +%s)
    if [ "$now" -ge "$deadline" ]; then
      echo "Background enrichment still active: $queue" >&2
      sqlite3 -readonly "$LIB/luminary.db" \
        "SELECT job_type, status, count(*) FROM enrichment_jobs GROUP BY 1, 2" >&2
      exit 1
    fi
    if [ "$now" -ge "$next_report" ]; then
      echo "  enrichment: $(jq -c '{pending, running}' <<<"$queue")"
      next_report=$(( now + 300 ))
    fi
    sleep 10
  done
fi

FAILED=()
if [ "$SUITE" = retrieval ] || [ "$SUITE" = all ]; then
  for d in "${RETRIEVAL[@]}"; do
    run --dataset "$d" --assert-thresholds || FAILED+=("$d")
  done
fi
if [ "$SUITE" = generation ] || [ "$SUITE" = all ]; then
  for d in "${GENERATION[@]}"; do
    run --dataset "$d" --judge-model "$EVAL_TEXT_MODEL" --check-citations --assert-thresholds \
      || FAILED+=("$d (generation)")
  done
fi
if [ "$SUITE" = cards ] || [ "$SUITE" = all ]; then
  # Report-only: the stored grounding verdicts on the cards ingestion wrote, before the
  # on-demand run adds its own.
  echo "Chapter cards written at ingestion, by grounding state:"
  curl -s -m30 "$URL/flashcards/grounding" | jq -c 'del(.changed)'
  (cd "$REPO" && UV_CACHE_DIR="$REPO/.uv-cache" uv run --no-sync --project "$REPO/backend" \
    python evals/run_flashcard_eval.py --dataset "$CARDS" --backend-url "$URL" \
    --judge-model "$EVAL_TEXT_MODEL" --assert-thresholds) || FAILED+=("$CARDS")
fi

echo "History: $STATE/scores_history.jsonl"
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "FAILED: ${FAILED[*]}" >&2
  exit 1
fi
