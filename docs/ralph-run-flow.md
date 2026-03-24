# Ralph Run Flow

This document describes the step-by-step cycle ralph follows when executing stories from a PRD.

Ralph is invoked as an AI agent (Claude) that reads a PRD file, finds the next unimplemented story,
implements it end-to-end, and loops until all stories pass. The flow below is the contract each run
must follow. Do not skip steps.

---

## Flowchart

```mermaid
flowchart TD
    A([Start: ralph invoked with PRD path]) --> B

    B[/"Read PRD\nprd-vN.json"/] --> C

    C{"Find first story\nwhere passes=false\nordered by priority"}
    C -->|No stories remaining| Z([Done -- all stories pass])
    C -->|Story SXXX found| D

    D[/"Read or create exec plan\ndocs/exec-plans/active/SXXX.md"/] --> E

    E["Explore codebase\nGlob + Grep + Read\nall relevant files"] --> F

    subgraph IMPLEMENT ["Implement"]
        direction TB
        F["Backend\nmodels.py + db_init.py migration\nservice layer\nrouter + API\npytest tests"]
        F --> G["Frontend\ncomponents + hooks\nZustand store changes\nVitest tests"]
    end

    G --> H

    subgraph GATES ["Quality Gates (run in order)"]
        direction TB
        H["uv run ruff check .\nfrom backend/"] --> I
        I["uv run pytest\nfrom backend/"] --> J
        J["npx tsc --noEmit\nfrom frontend/"]
    end

    J --> K{"All gates\npass?"}
    K -->|No -- fix then re-run gates| H
    K -->|Yes| L

    L[/"Run smoke test\nscripts/smoke/SXXX.sh"/] --> M

    M{"Smoke exits 0?"}
    M -->|No -- debug and fix| F
    M -->|Yes| N

    N["Run luminary-reviewer agent\n.claude/agents/luminary-reviewer"] --> O

    O{"Critical items\nreturned?"}
    O -->|Yes -- fix then re-run gates| H
    O -->|No| P

    P["Set passes=true in PRD\nAppend entry to progress.txt\nMove exec plan to completed/"] --> C
```

---

## Artifact Map

Each story SXXX produces or modifies these artifacts:

| Artifact | Location | When |
|---|---|---|
| Execution plan | `docs/exec-plans/active/SXXX.md` | Created before implementation starts |
| Backend changes | `backend/app/{models,services,routers}/` | During implement |
| DB migration | `backend/app/db_init.py` | During implement (if schema changes) |
| Backend tests | `backend/tests/test_*.py` | During implement |
| Frontend components | `frontend/src/components/` | During implement |
| Frontend pages | `frontend/src/pages/` | During implement (if page-level) |
| Smoke test | `scripts/smoke/SXXX.sh` | During implement |
| PRD update | `scripts/ralph/prd-vN.json` | After all gates pass (`passes: true`) |
| Progress log | `scripts/ralph/progress.txt` | After all gates pass |
| Completed plan | `docs/exec-plans/completed/SXXX.md` | After PRD update |

---

## Quality Gate Rules

1. **ruff**: zero warnings, zero errors. Fix linting before running tests -- failing lint masks test errors.
2. **pytest**: test count must not decrease from the regression baseline. Any drop is a regression -- stop and fix.
3. **tsc**: zero type errors. `any` is acceptable only when the upstream type is genuinely unknown; never cast to silence an error.
4. **smoke**: smoke tests verify the backend contract the UI depends on. A smoke test that only curls the new endpoint is insufficient when the story spans multiple API calls. See `docs/design-docs/story-authoring.md`.
5. **reviewer**: `luminary-reviewer` uses Sonnet. Critical items must be resolved. Warning items should be noted in progress.txt but do not block `passes: true`.

---

## Retry Rules

- Gate failure (ruff/pytest/tsc): fix then restart gates from ruff. Do not skip earlier gates.
- Smoke failure: fix backend logic, then re-run gates + smoke.
- Reviewer critical: fix then re-run gates + smoke + reviewer.
- Never set `passes: true` before smoke exits 0 and reviewer returns no Critical items.

---

## Version History

| Version | PRD | Branch | Stories |
|---|---|---|---|
| v2 | `scripts/ralph/prd-v2.json` | `ralph/luminary-v2` | S75-S160 (all pass) |
| v3 | `scripts/ralph/prd-v3.json` | `ralph/luminary-v3` | S161-S170 (Phase 1) |
```
