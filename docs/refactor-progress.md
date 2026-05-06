# Refactor TODOs (branch: feat/refac-1-luminary)

Active modularity refactor on this branch. Per the user's preference,
this file tracks **only what's still pending**. Completed work is in
`git log` (search for `refactor:` and `chore:` since the branch root).

## Next: audit #1 -- split `FlashcardService` (in progress)

- File: `backend/app/services/flashcard.py` (now 1,267 lines, was 2,054).
- Done: extracted `search` + FTS5 helpers (`_sanitize_fts5_query`,
  `_sync_flashcard_fts`, `_delete_flashcard_fts`) into
  `services/flashcard_search.py` as `FlashcardSearchService`.
  `FlashcardService(FlashcardSearchService)` preserves the call-site API
  for routers/tests; helpers are re-exported from `flashcard.py`.
- Done: extracted prompt strings + system-prompt builders into
  `services/flashcard_prompts.py` (FLASHCARD/NOTES/TECH/GAP/GRAPH/CLOZE
  templates, `_DIFFICULTY_GUIDELINES`, `_BOOK_CONTENT_GUIDELINE`,
  `_BLOOM_L3_INSTRUCTION`, `_TECH_TITLE_KEYWORDS`, `_infer_genre`,
  `_build_genre_system_prompt`); pure JSON parsers into
  `services/flashcard_parsers.py` (`_parse_llm_response`,
  `_parse_concept_extract`, `_parse_gap_flashcard`, `_parse_cloze_*`,
  `_build_cloze_question`, `_CLOZE_BLANK_RE`). Re-exported from
  `flashcard.py` for tests/routers.
- Done: collapsed `generate_from_gaps` and `generate_from_feynman_gaps`
  into shared `_run_gap_generation` (gap fan-out + parse + persist).
- Done: lifted `generate_technical` and `generate_cloze` into
  `services/flashcard_generators.py` as module-level async functions;
  `FlashcardService` thin-delegates. Generators indirect through
  `flashcard.get_llm_service` so existing test patches still apply.
- Remaining: `generate`, `generate_from_notes`, `generate_from_collection`,
  `generate_from_graph`. Same lift-to-module pattern; biggest payoff is
  `generate` itself.
- Refactor approach: split into `FlashcardGenerator` strategy family
  (one strategy per source), with shared `_build_prompt` /
  `_parse_llm_response` helpers already module-level (lines 446-712).
- Likely also drains several `noqa: PLC0415` inline imports (current
  count: 299 across `backend/app/`).

## Then: audit #2 -- split god routers

- `routers/study.py` (2,429 lines, 25 endpoints, 77 top-level defs):
  schemas (lines 117-445) move to `schemas/study.py`; helpers
  (`_compute_gaps:185`, `_compute_section_heatmap:356`,
  `_build_session_plan:441`) into existing `services/study_session_service.py`.
- Same problem in `documents.py:1714`, `notes.py:1377`, `flashcards.py:1002`.
- Mechanical but touches many files -- do it once `services/` is cleaner so
  this is not just shuffling.

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
