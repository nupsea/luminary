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
- **Caveat (added during plan refresh):** "DONE" here means
  schemas+helpers extracted, *not* that the routers are small. Current
  sizes: study.py 2,121, documents.py 1,467, notes.py 962,
  flashcards.py 787. The remaining bulk is endpoint bodies that talk
  to the session directly (audit #9) or orchestrate cross-service
  side effects. Audit #9 Phases 8-11 below address this; treat the
  per-router schema layer as the *floor* and continue extracting from
  the body when touching these routers for other reasons.

## Design principles (apply to every remaining phase)

Lessons distilled from audits #1, #2, #5, #6, #8, #9. Read these before
starting a new extraction so we don't re-derive them per phase.

1. **Re-export, don't break.** When code moves to a new module, keep the
   old name importable from its original home (`from old import X` ->
   `from new import X` with `# noqa: F401`). 7+ test files import nodes
   directly from `chat_graph`; routers import schemas from each other.
   The re-export is a one-line cost that buys silence from the test
   suite.
2. **Re-exports are name bindings, not call sites.** `mock.patch("old.X")`
   only intercepts code that calls through `old.X`. After a move, the
   real call site is `new.X`. When extracting, search for
   `patch("<module>.<symbol>")` and update the patch target -- failing
   to do this produces silent test drift (the patch applies but does
   nothing). See chat_graph phase 2 for the canonical example.
3. **Indirect through the original module for swappable singletons.**
   Things like `get_llm_service`, `get_retriever`, `get_graph_service`
   are routinely monkey-patched in tests. New modules should call them
   via `from app.services.X import get_Y` and invoke `get_Y()` at call
   time -- never bind the result at import time. This is what made the
   flashcard generator extraction safe.
4. **Schemas + helpers + body, in that order.** The God-router playbook
   that worked four times: (a) lift Pydantic schemas to
   `app/schemas/<entity>.py`; (b) lift pure helpers to
   `app/services/<entity>_service.py`; (c) only then split the body.
   Each of (a)-(c) ships independently; reviewers can sign off on one
   without holding up the others.
5. **Repos own session ops, services own logic, routers own HTTP.**
   When a router still has `session.execute` after a repo lands, that
   call is either (i) a complex multi-table transaction that genuinely
   belongs in the route, or (ii) a missed migration. Document which.
   The intentional-skip list in audit #9 is load-bearing -- copy it
   forward when adding new repos.
6. **Don't fight tightly-coupled orchestrators.** When you find a
   helper that flushes mid-transaction and fans out to FTS + vector +
   graph (e.g. `_apply_note_update`, `delete_document`), leave it in
   the router. The cost of "purifying" it exceeds the benefit; instead,
   put a comment on it explaining why it stays.
7. **Measure before and after.** Every phase commit message records
   line counts (e.g. `1,924 -> 1,565`). This makes regressions visible
   and turns the audit into a scoreboard. Future phases should do the
   same.
8. **Audit `# noqa: PLC0415` after every extraction.** Lazy imports
   were workarounds for circular deps. After a successful extraction
   the cycle is often broken; promote those imports to the top and
   delete the noqa. The total count is a *primary* health metric, not
   a side effect (now 293, was 299).

## Lower priority items from the audit (not yet started)

### #5 -- God class `KuzuService` (in progress -- 1,280 lines remain)
- `backend/app/services/graph.py` was 1,793 lines, now 1,280. Phases 1-3:
  - `KuzuConnection` (db + conn + lock + schema DDL,
    `services/graph_connection.py`).
  - `KuzuPrereqRepo` (`services/graph_prereq.py`, 7 methods).
  - `KuzuConceptRepo` (`services/graph_concept.py`, 3 methods).
  - KuzuService keeps the public method names and delegates;
    `_db / _conn / _lock` attributes preserved for back-compat
    (chat_graph reads `service._conn` directly).
- **Plan for the remaining 1,280 lines** (in priority order):
  - **Phase 4 -- `KuzuEntityRepo`** (`services/graph_entity.py`).
    Lift the 9 entity-CRUD methods that have *no* coupling to other
    repos: `upsert_entity`, `get_entities_by_type_for_document`,
    `upsert_document`, `add_mention`, `add_co_occurrence`,
    `add_relation`, `get_related_entity_pairs_for_document`,
    `get_co_occurring_pairs_for_document`, `match_entity_by_name`.
    Smallest, lowest-risk lift -- ~250 lines. Establishes the entity
    repo as the seam ViewRepo and TechRepo will read through.
  - **Phase 5 -- `KuzuTechRepo`** (`services/graph_tech.py`). The
    code-graph sub-system: `add_call_edge`, `add_tech_relation`,
    `add_version_of`, `get_entities_by_type`, `_get_diagram_nodes_by_type`,
    `upsert_diagram_node`, `add_diagram_edge`, `add_depicts_edge`,
    `get_diagram_nodes_for_document`, `get_diagram_edges_for_document`,
    `_get_tech_relation_edges`, `get_call_graph`. ~470 lines. Independent
    of view/prereq/concept; only depends on `KuzuConnection` and the new
    `KuzuEntityRepo`.
  - **Phase 6 -- `KuzuViewRepo`** (`services/graph_view.py`). The hard
    one: `get_graph_for_document`, `get_graph_for_documents`,
    `_get_note_nodes_for_entities`, `_get_co_occurrence_edges`,
    `get_entities_for_documents`, `get_cross_document_entities`. These
    *read across* prereq + concept + entity + tech to build the viz
    payload. Make ViewRepo a pure read-side aggregator that takes the
    other repos as constructor args; KuzuService becomes a 50-line
    facade that wires them together.
- **Out-of-scope cleanup that should land alongside Phase 6:**
  delete `_db / _conn / _lock` from KuzuService once `chat_graph`
  switches to `service.connection` (a properly-named accessor on
  `KuzuConnection`). This is a 2-line change in
  `chat_nodes/graph.py` -- safe to do now.
- **Acceptance criteria:** services/graph.py < 200 lines (pure
  facade); each repo < 500 lines; existing 100+ Kuzu tests still pass;
  `noqa: PLC0415` count in `app/runtime/chat_graph.py` and
  `app/runtime/chat_nodes/*.py` for `app.services.graph` drops to 0.

### #6 -- God workflow `runtime/chat_graph.py` (in progress)
- Was 1,924 lines, now 992. Phases:
  - Phase 1: `chat_nodes/_shared.py` -- system-prompt constants
    (`_SUMMARY_SYSTEM`, `_RELATIONAL_SYSTEM`, `_COMPARATIVE_SYSTEM`),
    `_get_system_prompt` selector, `_chunk_to_dict` / `_round_robin`
    helpers, and `_background_tasks` registry.
  - Phase 2: `chat_nodes/summary.py` -- `summary_node` + its four DB
    helpers (`_fetch_single_doc_executive_summary`,
    `_fetch_all_doc_executive_summaries`,
    `_fetch_library_executive_summary`,
    `_generate_library_summary_task`). Re-exported from `chat_graph.py`
    for back-compat with `from app.runtime.chat_graph import summary_node`.
    `test_confidence_fixes.py` patch path updated to point at
    `app.runtime.chat_nodes.summary._fetch_library_executive_summary`
    (the chat_graph re-export is a name binding, not the call site).
  - Phase 3: `chat_nodes/graph.py` -- `graph_node` +
    `_extract_entities_from_question`, `_query_kuzu_for_entity`, and the
    module-level `_ENTITY_RE` / `_CAPITALIZED_RE` regexes. Re-exported
    from `chat_graph.py`. `import re` dropped from chat_graph.py (no
    other use). 124 chat/confidence tests pass; ruff clean.
  - Phase 4: `chat_nodes/notes.py` -- `notes_node` + `notes_gap_node`.
    No mock.patch targets, clean lift.
  - Phase 5: `chat_nodes/socratic.py` -- `socratic_node` +
    `teach_back_node` + `_TEACH_BACK_SYSTEM`. Test patches in
    `test_chat_graph_socratic.py` (3) + `test_chat_graph_teach_back.py`
    (4) updated from `chat_graph.get_retriever` to
    `chat_nodes.socratic.get_retriever`. `LLMUnavailableError` import
    dropped from chat_graph.py.
  - Phase 6: `chat_nodes/comparative.py` -- `comparative_node` +
    `_decompose_comparison` + `_resolve_side_to_docs`. Test patches
    in `test_chat_graph_nodes.py` updated for both
    `_decompose_comparison` (mock_llm_calls fixture) and
    `get_retriever` (test_comparative_node_interleaves_results). 124
    chat/confidence tests pass; ruff clean.
- **Plan for the remaining 1,565 lines.** Order is by risk, lowest
  first. Each phase is one commit; no phase exceeds ~250 lines moved.
  - **Phase 4 -- `chat_nodes/notes.py`**: `notes_node` (~50 lines) +
    `notes_gap_node` (~140 lines). Self-contained; only shared
    helpers are `_chunk_to_dict` / `_round_robin` (already in
    `_shared`). No mock.patch targets to update.
  - **Phase 5 -- `chat_nodes/socratic.py`**: `socratic_node` +
    `teach_back_node` (~210 lines combined). Self-contained.
  - **Phase 6 -- `chat_nodes/comparative.py`**: `_decompose_comparison`,
    `_resolve_side_to_docs`, `comparative_node` (~235 lines). Watch
    for tests that patch `_decompose_comparison` -- grep first.
  - **Phase 7 -- `chat_nodes/search.py`**: `_fetch_section_summaries`,
    `_fetch_neighbor_chunks`, `search_node` (~165 lines). Same
    patch-path audit applies.
  - **Phase 8 -- `chat_nodes/synthesize.py`**: `_fetch_doc_titles_for_chunks`,
    `_fetch_section_ids_and_pages_for_chunks`,
    `_fetch_contradiction_context`, `synthesize_node` (~330 lines, the
    biggest single body). `synthesize_node` is also called from
    `augment_node` -- when extracting, route the augment call through
    the re-export so swapping models in tests still works.
  - **Phase 9 -- `chat_nodes/confidence.py`**: `confidence_gate_node`,
    `_route_after_confidence_gate`, `augment_node`, `web_augment_node`
    (~320 lines). After this lands, `chat_graph.py` should be < 400
    lines: classify_node, route_node, _route_after_strategy,
    build_chat_graph, get_chat_graph -- the StateGraph wiring only.
- **Acceptance criteria:** `chat_graph.py` < 400 lines; each
  `chat_nodes/*.py` < 350 lines; the 91+ chat_graph tests stay green;
  `import asyncio` / `import json` survive only if still used by the
  wiring layer (today: yes).
- **Stretch goal after phase 9:** rename `chat_graph.py` to
  `chat_workflow.py` and turn the package layout from
  `runtime/chat_graph.py + runtime/chat_nodes/` into a single
  `runtime/chat/{__init__.py, workflow.py, classify.py, route.py,
  nodes/...}.py`. Costs: many test imports change. Defer until #6 is
  otherwise complete; bundle as one rename commit.

### #7 -- 293 `noqa: PLC0415` inline imports (was 299)
- Signals circular deps and routers/services importing each other lazily.
  Real fix: thinner services, dependency-injected via `Depends()`, no
  service-to-service backreferences. Will partly fall out of #1 + #2.
- **Top offenders** (counted now, not when audit was written):
  `workflows/ingestion.py` (38), `routers/notes.py` (30),
  `routers/tags.py` (20), `runtime/chat_graph.py` (17),
  `services/image_enricher.py` (16), `routers/documents.py` (15),
  `services/flashcard_generators.py` (12),
  `services/clustering_service.py` (11), `app/main.py` (10),
  `services/image_extractor.py` (10), `services/flashcard.py` (10).
- **Plan -- categorise then drain in three passes:**
  1. **Workflow lazy-imports** (ingestion.py 38, chat_graph.py 17,
     flashcard_generators.py 12). Most are inside hot loops to avoid
     import-time cost; a chunk are circular workarounds. Pass 1: grep
     each `noqa: PLC0415`; for any whose target is now in a leaf
     module (no back-import), promote to top of file. Audits #5 and
     #6 phases above will retire ~30 of these mechanically.
  2. **Router-side circulars** (notes.py 30, tags.py 20,
     documents.py 15). These almost always trace back to
     `from app.routers.X import Y` -- a router importing another
     router for shared schemas. Fix path: lift the imported symbol to
     `app/schemas/<entity>.py` (audit #2 already created the homes).
  3. **Service-to-service late imports** (image_enricher 16,
     clustering 11, image_extractor 10, flashcard 10). Often
     `from app.services.A import get_a_service` inside a method to
     avoid a top-level cycle. Fix path: introduce a thin
     `app/services/_registry.py` that exposes `get_*` factories; both
     A and B import from `_registry`, never from each other.
- **Target by end of branch:** under 100 `noqa: PLC0415`. Past 100
  we declare an explicit allow-list in CLAUDE.md ("these are runtime
  optional imports and stay lazy") and re-enable PLC0415 globally.

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

### #9 -- 192 direct `session.execute/commit/add/delete` in routers (was 263)
- New layer: `backend/app/repos/`. Convention: one repo class per
  entity, owns all `session.execute/add/commit/delete` calls; routers
  depend via `Depends(get_X_repo)` and never touch the session.
- **Where the 192 remaining ops live** (counted now):
  `routers/study.py` (56), `routers/documents.py` (36),
  `routers/tags.py` (32), `routers/notes.py` (16),
  `routers/flashcards.py` (12), `routers/collections.py` (12),
  `routers/references.py` (6), `routers/reading.py` (6),
  `routers/sections.py` (4), `routers/chat_meta.py` (3),
  `routers/summarize.py` (2), `routers/search.py` (2),
  `routers/images.py` (2), `routers/code_executor.py` (2),
  `routers/admin.py` (1).
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
  remaining 192-direct-session count, but the highest-leverage
  routers are now repo-backed.
  Bigger entities (Note, Flashcard, Document) will need their existing
  services to also adopt the repo for consistency rather than keeping
  two paths.
- **Plan for the remaining 192 ops** (priority order):
  - **Phase 8 -- `StudyRepo`** (`backend/app/repos/study_repo.py`).
    Highest count, hardest shape -- 56 ops, mostly multi-table joins
    that drive the dashboard. Don't try to lift them all. Strategy:
    (a) extract the 4-5 reusable read patterns that show up in 3+
    routes (e.g. "list reviewed flashcards for date range",
    "session-plan join"); (b) keep the genuinely-bespoke
    cross-entity selects inline with a one-line comment explaining
    why. Target: cut study.py session ops to < 15 (remaining are
    documented bespoke). Will also unlock collapsing the 10
    "fetch+check+404" sites that audit #8 punted.
  - **Phase 9 -- extend `DocumentRepo`** to cover the 36 remaining
    documents.py ops. Most are `delete_document`'s 18-table cascade
    -- which we *should not* lift wholesale. Better approach: split
    that endpoint into `DocumentDeletionService` (a service, not a
    repo) that orchestrates 7-8 named steps; the service uses the
    repos. Net effect: documents.py drops to ~15 ops (the genuinely
    transactional ones).
  - **Phase 10 -- extend `TagRepo`** to cover the 32 remaining
    tags.py ops. The skipped routes are `merge_tags`,
    `accept_normalization_suggestion`, `migrate-naming` -- all
    multi-entity transactions. Same pattern as Phase 9: introduce a
    `TagMergeService` that orchestrates the bespoke rollback logic
    and uses `TagRepo` + `NoteRepo` for the underlying ops.
  - **Phase 11 -- mechanical sweep** of the small-count routers
    (references 6, reading 6, sections 4, chat_meta 3, summarize 2,
    search 2, images 2, code_executor 2, admin 1). Most should map
    cleanly onto existing repos or motivate one new repo each
    (e.g. `SectionRepo`). Target: zero session ops in any router
    < 10 lines after this phase.
- **Acceptance criteria:** total router-side session ops < 50; every
  remaining inline op has a one-line comment explaining why it's
  inline (transactional, custom join shape, etc.); a regression test
  in CI greps for new `session.execute(` introductions in routers
  and warns.

### #11 -- God pages (frontend)
- Current line counts (re-measured): `pages/Study.tsx` (2,255),
  `pages/Viz.tsx` (1,757), `pages/Monitoring.tsx` (1,361),
  `pages/Notes.tsx` (1,313), `pages/Chat.tsx` (1,301),
  `components/reader/DocumentReader.tsx` (1,290),
  `pages/Learning.tsx` (1,134), `components/NoteReaderSheet.tsx`
  (1,039), `components/TeachbackSession.tsx` (1,020).
- **Pattern guide -- write this once, apply to every page.** Three
  extractions, in order, per page:
  1. **State hook**: pull all `useState`/`useEffect`/`useCallback`
     into `usePageNameState.ts` co-located with the page. The page
     becomes a layout component that consumes the hook.
  2. **Sub-route components**: every `<Tabs>` panel, every modal /
     drawer / sheet, every "section" with > 50 lines becomes a sibling
     `pages/PageName/<Section>.tsx`. The page becomes a router-like
     `switch (activeTab)`.
  3. **Network layer**: every `fetch(...)` (see #12) graduates to
     `frontend/src/lib/<page>Api.ts` with typed request/response.
- **Plan, in priority order** (one PR per page):
  - **Phase A -- `pages/Study.tsx`** (2,255 -> target < 400).
    Biggest file in the entire frontend. Three sub-routes inside it:
    "session", "review", "decks". Extract each to
    `pages/Study/{SessionPanel,ReviewPanel,DecksPanel}.tsx`. Keep
    the URL params parsing in the parent. Expect ~30 fetch sites to
    drain into `lib/studyApi.ts` (already exists, partially used).
  - **Phase B -- `pages/Viz.tsx`** (1,757). Sigma graph rendering;
    extract `<GraphCanvas>`, `<ScopeSelector>`, `<NodeDrawer>` as
    siblings. Pure-render extracts are low-risk.
  - **Phase C -- `pages/Notes.tsx`** (1,313). Three columns:
    note-list, note-editor, note-graph-mini. Each becomes a sibling.
    `NoteReaderSheet` (1,039) is already a sibling but has the same
    god-component problem -- handle in same PR.
  - **Phase D -- `pages/Monitoring.tsx`** (1,361). Dashboard tabs;
    one component per tab + a shared `useMonitoringPolling` hook for
    the live-data refresh.
  - **Phase E -- `pages/Chat.tsx`** (1,301). Streaming SSE handler
    is the gnarly part; it should live in
    `lib/chatStreamClient.ts` (a class with start/cancel/onChunk),
    not in the page.
- **Acceptance criteria:** every page < 500 lines; every page has at
  most 3 imports of `fetch` (and ideally 0 -- see #12); each page has
  a vitest smoke test that mounts it with mocked api and asserts the
  three primary tabs render.

### #12 -- 248 direct `fetch()` calls outside `frontend/src/lib/` (was 263)
- The api-module pattern (`*Api.ts`) is followed inconsistently. Pick
  one and migrate so error/auth handling stops being duplicated.
- **Existing api modules to standardise on:** `studyApi.ts`,
  `goalsApi.ts`, `focusApi.ts`, `chatSessionsApi.ts`,
  `ingestionApi.ts`. Audit each: pick the one with the cleanest
  contract (typed response, single error shape, no inline URL
  building) and promote its conventions to a shared
  `frontend/src/lib/apiClient.ts`.
- **Plan:**
  1. **Define `apiClient.ts`** (~80 lines): a single `request<T>(
     path, init)` that handles base URL, JSON encoding, error
     mapping (-> custom `ApiError` with `status` + `code` + `body`),
     and timeout. Add a `useApi()` hook for components that want
     loading/error state (or just stick with raw try/catch -- pick
     one).
  2. **Migrate by surface area**, top-traffic first: all reader
     components (DocumentReader, ReadView, EPUBViewer, PDFViewer,
     SectionListItem) -> `lib/readerApi.ts`. Then all dialogs ->
     existing per-feature api modules. Then the long tail.
  3. **Lint rule** (`.eslintrc` overrides): forbid `fetch(` outside
     `frontend/src/lib/**`. Ratchet -- start as a warning, flip to
     error once the count hits 0.
- **Acceptance criteria:** zero `fetch(` in `frontend/src/{pages,
  components}/**`; one error-mapping path; eslint enforces it.

### #13 -- God workflow `workflows/ingestion.py` (NEW -- not on
original audit)
- File is 1,832 lines, 11 graph nodes plus 5 helper coroutines plus
  the `IngestionState` TypedDict and graph wiring. Same shape problem
  as `chat_graph.py` before audit #6 began.
- **Plan -- mirror the chat_nodes layout:**
  1. Create `workflows/ingestion_nodes/_shared.py` for
     `IngestionState`, `_classify`, `_update_stage`, and the
     `build_entity_tail` helper that several nodes import.
  2. One module per node, each ~100-300 lines: `parse.py`,
     `classify.py`, `transcribe.py`, `chunk.py` (the biggest --
     contains `_chunk_book`, `_chunk_tech_book`, `_chunk_conversation`,
     `_chunk_audio`, `_chunk_code_file`), `embed.py`,
     `keyword_index.py`, `entity_extract.py` (contains
     `_build_call_graph`), `section_summarize.py`, `summarize.py`,
     `error_finalize.py`, `enrichment_enqueue.py`.
  3. `ingestion.py` shrinks to wiring: graph build + `run_ingestion`
     entrypoint + `_route_on_status`.
- **Acceptance criteria:** `ingestion.py` < 300 lines; each
  `ingestion_nodes/*.py` < 350 lines; the 38 `noqa: PLC0415` in this
  file drop to < 5; existing ingestion tests stay green.

### #14 -- `services/retriever.py` (874 lines), `services/summarizer.py`
(696 lines), `services/feynman_service.py` (636 lines) (NEW)
- These three services are now the largest non-router/non-workflow
  files after the audit-#1 split. They're not God classes per se but
  each mixes orchestration with implementation in a way that
  testing keeps tripping on (lots of `mock.patch` on private helpers).
- **No commitment yet -- decide after #5/#6/#13 land.** If the
  re-export + indirect-singleton pattern is paying off, apply it
  here too: split each into `<service>.py` (public class) +
  `<service>_strategies.py` (the swappable bits). Otherwise leave.

### #15 -- TypeScript model duplication (NEW)
- Many `*.ts` files re-declare API response types inline (e.g.
  `type FlashcardResponse = { id: string; ... }` in 6+ components).
  When the backend Pydantic schema changes, the frontend silently
  drifts.
- **Plan:** auto-generate a `frontend/src/types/api.ts` from the
  FastAPI OpenAPI schema (`uvx openapi-typescript`); replace inline
  types with imports. Add a make/justfile target so it runs as part
  of `npm run check`. Low effort, high payoff -- worth doing
  before the per-page extractions in #11 so the new sub-components
  pick up the canonical types.

## Recommended execution order

The above sections are organised by topic. The actual order in which
to land them maximises early payoff and keeps each commit small enough
to review:

1. **Finish #6 chat_graph** (Phases 4-9). Lowest risk, highest
   ratio of mechanical-lift to design-work; restores the chat workflow
   to a readable wiring layer.
2. **#13 ingestion** Phases 1-3. Same playbook as #6, applied to the
   second-largest file in the backend. Will retire ~30 PLC0415 noqas
   on its own.
3. **#5 KuzuService** Phases 4-6. Now that #6 and #13 have proven the
   re-export pattern under load, the harder ViewRepo / TechRepo split
   has a known-good template.
4. **#15 TypeScript codegen.** One-time setup; unlocks #11 (god pages)
   without churning types twice.
5. **#11 god pages**, in the order Study -> Viz -> Notes ->
   Monitoring -> Chat. Phase A (Study) is the biggest single payoff
   in the entire branch.
6. **#12 fetch standardisation.** Bundle with #11 where it overlaps
   (each page's fetch sites move into a `*Api.ts` as part of the
   page split), then mop up the rest in one sweep + add the eslint
   rule.
7. **#9 session-ops residual** (Phases 8-11). Defer until last; the
   highest-leverage routers are already done, and #5/#6 will retire
   some of these as side effects.
8. **#7 PLC0415 sweep.** This is the *outcome* of all the above plus
   one targeted pass at the end. Don't chase it directly -- chase
   the structural fixes and watch the count fall.
9. **#14** is exploratory; only start if there's clear pain after the
   above eight items land.

## Pre-existing test failures (do not chase unless asked)

- Frontend `vitest`: 11 failures in `pdfHighlightOverlay.test.ts` and
  `pdfTocUtils.test.ts` (same with refactor stashed -- pre-date this work).
- Backend `pytest`: `test_pomodoro_service::test_stats_only_completed_count_total`
  is date-flaky (`assert 1 == 2` for `today_count`).
- Backend `tsc -p tsconfig.app.json`: `src/components/evals/AblationsTab.tsx`
  (recharts type) and `src/pages/Admin.tsx` (unused `Legend` import).
