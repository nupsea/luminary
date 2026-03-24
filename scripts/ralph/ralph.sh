#!/usr/bin/env bash
# ralph.sh -- Luminary AI agent loop
#
# Usage:
#   ./scripts/ralph/ralph.sh --tool claude <max_budget_usd>
#
# Examples:
#   ./scripts/ralph/ralph.sh --tool claude 12    # implement next story, $12 budget cap
#   ./scripts/ralph/ralph.sh --tool claude 60    # implement next story, $60 budget cap
#
# The script finds the first story with passes=false (ordered by priority),
# invokes the selected tool with a full implementation prompt, then loops
# until no more stories remain or the budget is consumed.
#
# Permissions: runs claude with --dangerously-skip-permissions so the agent
# can read/write files and run shell commands without pausing for approval.
# Only run this in the Luminary repo on your local machine.

set -euo pipefail

TOOL="claude"
MAX_BUDGET=12
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ── parse args ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --tool) TOOL="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,18p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    [0-9]*) MAX_BUDGET="$1"; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ── detect active PRD from git branch ────────────────────────────
BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
case "$BRANCH" in
  ralph/luminary-v3) PRD="$REPO_ROOT/scripts/ralph/prd-v3.json" ;;
  ralph/luminary-v2) PRD="$REPO_ROOT/scripts/ralph/prd-v2.json" ;;
  *)                 PRD="$REPO_ROOT/scripts/ralph/prd-v3.json" ;;
esac

echo "==> Ralph"
echo "    tool      : $TOOL"
echo "    budget    : \$$MAX_BUDGET"
echo "    branch    : $BRANCH"
echo "    prd       : $PRD"
echo ""

# ── find next pending story ───────────────────────────────────────
find_next_story() {
  python3 - <<PYEOF
import json, os, sys
with open(os.environ['PRD_PATH']) as f:
    prd = json.load(f)
pending = [s for s in prd['stories'] if not s.get('passes', False)]
pending.sort(key=lambda s: s['priority'])
if pending:
    s = pending[0]
    print(f"{s['id']}|||{s['title'][:70]}|||{s['priority']}|||{len(pending)}")
PYEOF
}

export PRD_PATH="$PRD"
RAW=$(find_next_story)

if [[ -z "$RAW" ]]; then
  echo "==> All stories pass. Nothing to do."
  exit 0
fi

STORY_ID=$(echo "$RAW" | cut -d'|' -f1)
STORY_TITLE=$(echo "$RAW" | cut -d'|' -f4)
PRIORITY=$(echo "$RAW" | cut -d'|' -f7)
REMAINING=$(echo "$RAW" | cut -d'|' -f10)

echo "==> Next story : $STORY_ID (P${PRIORITY}) -- $STORY_TITLE"
echo "==> Remaining  : $REMAINING stories pending"
echo ""

# ── build the implementation prompt ──────────────────────────────
PROMPT="You are Ralph, the Luminary implementation agent.

Your task is to implement story $STORY_ID from the PRD at:
  $PRD

Follow the ralph run flow contract in:
  $REPO_ROOT/docs/ralph-run-flow.md

Read the codebase patterns before touching any code:
  $REPO_ROOT/scripts/ralph/patterns.md

== Step-by-step ==

1. Read story $STORY_ID from the PRD (full description + all acceptance criteria).

2. Create or read the execution plan at:
     $REPO_ROOT/docs/exec-plans/active/${STORY_ID}.md
   If it does not exist, create it now (title, goal, file list, step sequence).

3. Explore the codebase -- read every file you will touch before writing any code.
   Skipping this step causes regressions.

4. Implement backend changes:
   - models.py  (SQLAlchemy models if schema changes)
   - db_init.py (DDL migration if new tables/indexes)
   - service layer in backend/app/services/
   - router in backend/app/routers/
   - pytest tests in backend/tests/

5. Implement frontend changes:
   - components in frontend/src/components/
   - page files in frontend/src/pages/ if needed
   - Zustand store additions in frontend/src/store/
   - Vitest tests

6. Run quality gates IN ORDER -- stop and fix before moving on:
   a. cd $REPO_ROOT/backend && uv run ruff check .
   b. cd $REPO_ROOT/backend && uv run pytest
   c. cd $REPO_ROOT/frontend && npx tsc --noEmit
   If any gate fails, fix the errors then restart from gate (a).

7. Run the smoke test. If it does not exist, create it:
     $REPO_ROOT/scripts/smoke/${STORY_ID}.sh
   The smoke script must verify the full observable contract:
   curl each new endpoint, check HTTP status, and assert key response fields.
   Run it: bash $REPO_ROOT/scripts/smoke/${STORY_ID}.sh
   If it fails, fix the root cause then re-run gates + smoke.

8. When all gates pass and smoke exits 0:
   - Set passes=true for $STORY_ID in $PRD
   - Append one line to $REPO_ROOT/scripts/ralph/progress.txt:
       $(date +%Y-%m-%d) $STORY_ID DONE  <one-sentence summary>
   - Move $REPO_ROOT/docs/exec-plans/active/${STORY_ID}.md to
       $REPO_ROOT/docs/exec-plans/completed/${STORY_ID}.md

Do NOT set passes=true before smoke exits 0.
Do NOT skip the exec plan step -- it is the alignment checkpoint.
Do NOT use pip, Poetry, or npm install (uv and the existing node_modules only)."

# ── invoke the tool ───────────────────────────────────────────────
case "$TOOL" in
  claude)
    claude \
      --dangerously-skip-permissions \
      --max-budget-usd "$MAX_BUDGET" \
      --add-dir "$REPO_ROOT" \
      -p "$PROMPT"
    ;;
  *)
    echo "Unknown tool: $TOOL (only 'claude' supported)"
    exit 1
    ;;
esac

# ── verify story was marked done ──────────────────────────────────
DONE=$(python3 - <<PYEOF
import json, os
with open(os.environ['PRD_PATH']) as f:
    prd = json.load(f)
s = next((s for s in prd['stories'] if s['id'] == '$STORY_ID'), None)
print('yes' if s and s.get('passes') else 'no')
PYEOF
)

echo ""
if [[ "$DONE" == "yes" ]]; then
  echo "==> $STORY_ID marked passes=true. Run ralph again for the next story."
else
  echo "==> WARNING: $STORY_ID did not reach passes=true within the budget."
  echo "    Increase the budget or debug the failure, then re-run."
  exit 1
fi
