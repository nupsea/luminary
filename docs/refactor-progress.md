# Refactor TODOs (branch: feat/refac-1-luminary)

Active modularity refactor on this branch. Per the user's preference,
this file tracks **only what's still pending**. Completed work is in
`git log` (search for `refactor:` and `chore:` since the branch root).

## audit #1 -- split `FlashcardService` (DONE)

- File: `backend/app/services/flashcard.py` is now 718 lines (was 2,054).
- Done: extracted `search` + FTS5 helpers (`_sanitize_fts5_query`,
  `_sync_flashcard_fts`, `_delete_flashcard_fts`) into
  `services/flashcard_search.py` as `FlashcardSearchService`.
  `FlashcardService(FlashcardSearchService)` preserves the call-site API
  for routers/tests; helpers are re-exported from `flashcard.py`.
- Done: extracted prompt strings + system-prompt builders into
  `services/flashcard_prompts.py`; pure JSON parsers into
  `services/flashcard_parsers.py`. Re-exported from `flashcard.py` for
  tests/routers.
- Done: collapsed `generate_from_gaps` and `generate_from_feynman_gaps`
  into shared `_run_gap_generation` (gap fan-out + parse + persist).
- Done: lifted all eight generation methods (`generate`,
  `generate_from_notes`, `generate_from_collection`, `generate_from_graph`,
  `generate_technical`, `generate_cloze`) into
  `services/flashcard_generators.py` as module-level async functions.
  `FlashcardService` is now thin delegations only (the gap pair stays as
  service methods because they share `_run_gap_generation`). Generators
  indirect through `flashcard.get_llm_service` so test patches keep
  working.
- Net: flashcard.py is 35 % of its original size; remaining helpers in
  `flashcard.py` are document/chunk plumbing (`_fetch_chunks`, `_build_text`,
  `_classify_chunk`, etc.) that several generators import.
- Refactor approach: split into `FlashcardGenerator` strategy family
  (one strategy per source), with shared `_build_prompt` /
  `_parse_llm_response` helpers already module-level (lines 446-712).
- Likely also drains several `noqa: PLC0415` inline imports (current
  count: 299 across `backend/app/`).

## audit #2 -- split god routers (in progress)

- `routers/study.py` 2,472 -> 2,123 lines. Done:
  - All 36 Pydantic schemas extracted to new `app/schemas/study.py`.
  - Pure helpers (`compute_gaps`, `compute_section_heatmap`,
    `build_session_plan`) extracted to new
    `app/services/study_session_service.py`.
  - `routers/study.py` re-exports the schemas + helpers (under their
    private aliases) via `__all__` so existing imports in `feynman.py`
    and tests keep working.
- Remaining for audit #2: `documents.py:1714`, `notes.py:1377`,
  `flashcards.py:1002` -- same pattern.

## Lower priority items from the audit (not yet started)

### #5 -- God class `KuzuService`
- `backend/app/services/graph.py:60`. 41 methods on one class, file is
  1,758 lines. Cleanly splits into `KuzuPrereqRepo`, `KuzuConceptRepo`,
  `KuzuViewRepo` over a shared `KuzuConnection`.

### #6 -- God workflow `runtime/chat_graph.py`
- 1,871 lines, 34 node fns. Refactor: one file per node group under
  `runtime/chat_nodes/` with a thin `chat_graph.py` that just wires them.

### #7 -- 299 `noqa: PLC0415` inline imports
- Signals circular deps and routers/services importing each other lazily.
  Real fix: thinner services, dependency-injected via `Depends()`, no
  service-to-service backreferences. Will partly fall out of #1 + #2.

### #8 -- "fetch + check + 404" boilerplate (115 sites)
- Extract `repo.get_or_404(model, id, name)` helpers.

### #9 -- 263 direct `session.execute/commit/add/delete` in routers
- Push into per-entity Repo modules under a new `repos/` layer (does
  not exist yet, only `services/`).

### #11 -- God pages
- `pages/Study.tsx` (2,190), `pages/Notes.tsx` (1,318),
  `pages/Monitoring.tsx` (1,313), `pages/Chat.tsx` (1,291). Apply the
  same Phase A pattern as DocumentReader: extract inline subcomponents
  into siblings.

### #12 -- 263 direct `fetch()` calls outside `frontend/src/lib/`
- The api-module pattern (`*Api.ts`) is followed inconsistently. Pick
  one and migrate so error/auth handling stops being duplicated.

## Pre-existing test failures (do not chase unless asked)

- Frontend `vitest`: 11 failures in `pdfHighlightOverlay.test.ts` and
  `pdfTocUtils.test.ts` (same with refactor stashed -- pre-date this work).
- Backend `pytest`: `test_pomodoro_service::test_stats_only_completed_count_total`
  is date-flaky (`assert 1 == 2` for `today_count`).
- Backend `tsc -p tsconfig.app.json`: `src/components/evals/AblationsTab.tsx`
  (recharts type) and `src/pages/Admin.tsx` (unused `Legend` import).
