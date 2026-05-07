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

### #5 -- God class `KuzuService` (in progress)
- `backend/app/services/graph.py` was 1,793 lines, now 1,264. Phases 1-3:
  - `KuzuConnection` (db + conn + lock + schema DDL,
    `services/graph_connection.py`).
  - `KuzuPrereqRepo` (7 methods: add_prerequisite,
    get_prerequisite_edges_for_document,
    add_prerequisite_with_section, has_prerequisite_edges,
    get_entry_point_concepts, get_prerequisite_edges_for_graph,
    get_learning_path -- in `services/graph_prereq.py`).
  - `KuzuConceptRepo` (3 methods: add_same_concept_edge,
    get_same_concept_edges, get_concept_clusters -- in
    `services/graph_concept.py`).
  - KuzuService keeps the public method names and delegates;
    `_db / _conn / _lock` attributes preserved for back-compat
    (chat_graph reads `service._conn` directly).
- Remaining phases (deferred -- view/tech sub-repos couple to
  prereq/concept via service-level orchestration; clean extraction
  needs an interface-design pass beyond mechanical lift):
  KuzuViewRepo (get_graph_for_document /_documents,
  _get_note_nodes_for_entities, _get_co_occurrence_edges),
  KuzuTechRepo (CALLS / IMPLEMENTS / VERSION_OF / Diagram*).

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
- Proof-of-pattern + first fan-out:
  - `ClipRepo` -- 7 unit tests + 6 endpoint contract tests pass.
  - `AnnotationRepo` -- 4 unit tests + 4 endpoint tests pass.
  - `CollectionRepo` -- 10 unit tests; 24 existing collection +
    collection-health endpoint tests pass. (Migrate-naming endpoint
    keeps inline session ops for now -- one-shot migration with
    bespoke merge logic.)
  - `TagRepo` -- 9 unit tests; 42 existing tag tests pass. Migrated
    routes: list, autocomplete, tree, create, get_notes_for_tag,
    update, delete. `merge_tags`,
    `accept_normalization_suggestion`, and `migrate-naming` keep inline
    session ops -- multi-entity transactional flows with bespoke
    rollback semantics (same exception applied to CollectionRepo's
    migrate-naming).
  - `NoteRepo` -- 9 unit tests; 46 existing notes/note-links/multi-doc
    tests pass. Covers `NoteModel` + `NoteLinkModel` + `NoteSourceModel`
    reads. Migrated routes: dedup-on-create, delete, get,
    autocomplete, get_note_links, create_note_link, delete_note_link,
    cluster-trigger count, suggest_tags, plus `_apply_note_update`'s
    get_or_404 + collection_ids fetch. Inline (intentional): `list_notes`
    (custom multi-table filter), `_apply_note_update` orchestration
    (mid-transaction flush + FTS/vector/graph fan-out), the dual
    NoteSourceModel/CollectionMember bulk reads inside list_notes,
    flashcard preview/list (other entities), gap_detect, suggest_title.
  - `FlashcardRepo` -- 8 unit tests; 52 existing flashcard / FSRS /
    search / source-context tests pass. Migrated routes: list (with
    optional bloom + section join), update, delete, bulk_delete,
    delete_all_document_flashcards, export-csv card load,
    get_source_context get_or_404. Inline (intentional):
    create_trace_flashcard (FTS sync mid-tx), list_flashcard_decks
    (custom GROUP BY + collection-name source-type derivation),
    review (cross-service FSRS + ReviewEvent + XP), get_source_context
    chunk/section/doc joins.
  - `DocumentRepo` -- 5 unit tests; 39 existing document / search tests
    pass. Migrated routes: ingest dedup-by-file-hash, get_document
    (sections + read count), get_document_chunks, patch_document,
    patch_document_tags. Inline (intentional): list_documents (10+
    correlated scalar subqueries for derived fields -- not reusable),
    delete_document (cascading delete across 18 child tables +
    LanceDB + Kuzu + filesystem orchestration), and the many endpoints
    that read child entities directly via their own session block.
- Fan-out done: ClipRepo, AnnotationRepo, CollectionRepo, TagRepo,
  NoteRepo, FlashcardRepo, DocumentRepo. Audit #9 still tracks the
  remaining 263-direct-session count, but the highest-leverage
  routers are now repo-backed.
  Bigger entities (Note, Flashcard, Document) will need their existing
  services to also adopt the repo for consistency rather than keeping
  two paths.

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
