# Ralph Agent Instructions

You are an autonomous coding agent implementing Luminary stories.

## Your Task

1. Read the active PRD -- detect it from the current git branch:
   - branch `ralph/luminary-v3` -> `scripts/ralph/prd-v3.json`
   - branch `ralph/luminary-v2` -> `scripts/ralph/prd-v2.json`

2. Read `scripts/ralph/progress.txt` -- check the **Codebase Patterns** section first.

3. Read `scripts/ralph/patterns.md` -- stable patterns accumulated across all stories.
   Never skip this step; it prevents repeating known mistakes.

4. Confirm you are on the correct branch listed in the PRD `branchName` field.
   If not, check it out or create it from master.

5. Pick the **lowest priority number** story where `passes: false`.
   (Priority 1 = implement first; do not skip ahead.)

6. Read or create the execution plan at `docs/exec-plans/active/<STORY_ID>.md`.
   If it does not exist, create it now: title, goal, files to touch, step sequence.

7. Explore the codebase -- read every file you will modify before writing any code.
   Skipping exploration causes regressions.

8. Implement the story:
   - Backend: models.py, db_init.py, service layer, router, pytest tests
   - Frontend: components, hooks, Zustand store additions, Vitest tests

9. Run quality gates IN ORDER -- fix failures before proceeding:
   a. `cd backend && uv run ruff check .`
   b. `cd backend && uv run pytest`
   c. `cd frontend && npx tsc --noEmit`
   If any gate fails, fix the errors and restart from gate (a).

10. Run the smoke test. Create it if it does not exist:
    `scripts/smoke/<STORY_ID>.sh`
    The smoke script must curl each new endpoint and assert HTTP status + key fields.
    Run: `bash scripts/smoke/<STORY_ID>.sh`
    If it fails, fix the root cause then re-run gates + smoke.

11. When all gates pass and smoke exits 0:
    - Set `passes: true` for this story in the PRD
    - Commit ALL changes: `feat: <STORY_ID> - <Story Title>`
    - Move `docs/exec-plans/active/<STORY_ID>.md` to `docs/exec-plans/completed/`

12. Append your progress to `scripts/ralph/progress.txt` (never replace, always append):

```
## <Date/Time> - <STORY_ID>
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered
  - Gotchas encountered
  - Useful context
---
```

13. If you discover a **reusable pattern**, add it to `scripts/ralph/patterns.md`
    (update in-place, do not append chronologically).

## Quality Requirements

- Do NOT set `passes: true` before smoke exits 0
- Do NOT commit broken code
- Do NOT use pip, Poetry, or `npm install` -- use uv and the existing node_modules only
- Keep changes focused and minimal; follow existing code patterns

## Stop Condition

After completing a story, check if ALL stories in the PRD have `passes: true`.

If ALL stories are complete, reply with exactly:
<promise>COMPLETE</promise>

If stories remain with `passes: false`, end your response normally.
The next ralph iteration will pick up the next story.

## Important

- Work on ONE story per iteration
- Read patterns.md and progress.txt before every story
- Keep CI green
