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

## audit #2 -- split god routers (DONE)

- `routers/study.py` 2,472 -> 2,123 lines. Done:
  - All 36 Pydantic schemas extracted to new `app/schemas/study.py`.
  - Pure helpers (`compute_gaps`, `compute_section_heatmap`,
    `build_session_plan`) extracted to new
    `app/services/study_session_service.py`.
  - `routers/study.py` re-exports the schemas + helpers (under their
    private aliases) via `__all__` so existing imports in `feynman.py`
    and tests keep working.
- `routers/documents.py` 1,749 -> 1,550 lines. Done:
  - All 24 Pydantic schemas extracted to new `app/schemas/documents.py`.
  - Pure helpers (`_delete_raw_file`, `_safe_tags`, `_section_to_dict`,
    `_parsed_to_dict`, `_derive_learning_status`) extracted to new
    `app/services/documents_service.py`.
  - `routers/documents.py` re-exports them under their private aliases
    via `__all__` so `routers/study.py` (5 import sites) and
    `tests/test_documents.py` keep working.
- `routers/notes.py` 1,394 -> 1,062 lines. Done:
  - All 26 Pydantic schemas extracted to new `app/schemas/notes.py`.
  - Pure helpers (`_to_response`, `_fts_insert`, `_fts_delete`, `_fts_update`,
    `_sync_tag_index`, `_sync_note_sources`, `_upsert_note_graph`,
    `_embed_and_store_note`) extracted to new `app/services/notes_service.py`.
  - `routers/notes.py` re-exports them under their private aliases via
    `__all__` so `routers/tags.py` (3 import sites of `_sync_tag_index`)
    and `tests/test_naming_migration.py` keep working.
  - `_apply_note_update` stays in the router because it is tightly coupled
    to module-level `_background_tasks` and orchestrates the lifted
    helpers via fire-and-forget tasks.
- `routers/flashcards.py` 1,005 -> 833 lines. Done:
  - All 22 Pydantic schemas extracted to new `app/schemas/flashcards.py`.
  - Pure helpers (`_to_response`, `_cards_to_csv`) extracted to new
    `app/services/flashcards_router_service.py` (named `_router_` to
    avoid clashing with the existing `flashcard_*` services).
  - `routers/flashcards.py` re-exports them under their private aliases
    via `__all__` so `routers/study.py` (imports `_to_response` and
    `FlashcardResponse`) and `tests/test_flashcard_s188.py` keep working.
  - `schemas/study.py` redirected to import `FlashcardResponse` directly
    from `schemas/flashcards` to avoid the router round-trip.
- audit #2 complete -- all four god routers (study, documents, notes,
  flashcards) now follow the schemas-and-services split.

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

### #8 -- "fetch + check + 404" boilerplate (DONE -- mechanical pass)
- Helper landed at `backend/app/services/repo_helpers.py`:
  `get_or_404(session, model, id, *, name=...)` and
  `require_or_404(obj, name)` (for already-fetched rows).
- Migrated: `clips.py`, `documents.py`, `tags.py`, `references.py`,
  `flashcards.py`, `notes.py`, `study.py` (1), `collections.py`,
  `images.py`, `annotations.py`, `reading.py`, `summarize.py`. ~50 sites
  collapsed; net ~−170 lines across routers.
- Intentionally skipped:
  - `goals.py` -- 404s are `GoalNotFound` exception-to-HTTP mappings.
  - `evals.py` -- already uses `db.get(Model, id)` + 2-line None check;
    the helper would be a wash.
  - `chat_sessions.py` -- service-layer returns None; not a fetch+check
    pattern. Could use `require_or_404` but minimal win.
  - `study.py` (10 multi-line selects with joins) -- non-uniform shapes;
    leave to a follow-up if/when those endpoints are touched again.

### #9 -- 263 direct `session.execute/commit/add/delete` in routers
- New layer: `backend/app/repos/`. Convention: one repo class per
  entity, owns all `session.execute/add/commit/delete` calls; routers
  depend via `Depends(get_X_repo)` and never touch the session.
- Proof-of-pattern: `ClipRepo` + `routers/clips.py` migration.
  - 7 unit tests in `tests/test_clip_repo.py` exercise the repo
    directly (in-memory engine fixture).
  - All 6 existing `test_clips_api.py` endpoint tests still pass --
    HTTP contract unchanged.
- Fan-out order (next): `AnnotationRepo`, `NoteRepo`, `FlashcardRepo`,
  `CollectionRepo`, `TagRepo`, `DocumentRepo`. Bigger entities (Note,
  Flashcard, Document) will need their existing services to also adopt
  the repo for consistency rather than keeping two paths.

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
