# Refactor Progress (branch: feat/refac-1-luminary)

Tracks the multi-step modularity refactor kicked off from the read-only audit.
Each completed item links to the commit that lands it.

## Done

### 1. Comment cleanup (option 3 of original plan) — done on `feat/attention_streak`
- 103 files, 1,825 line deletions, 0 insertions.
- Removed banner-divider blocks (`# ---`) and `# Step N` / `# Phase N` narrations.
- Preserved load-bearing comments: 14 FastAPI `# NOTE: ... registered BEFORE`
  ordering invariants, the cache-fallback warning in `summarizer.py`, and the
  OS-keychain TODO with tracker reference.

### 2. LLM gateway centralization (audit #3 + #4) — `74ef6ed`
- Extended `services/llm.py` with `complete(messages, ...)` and
  `stream_messages(messages, ...)` that share the existing telemetry +
  Langfuse path with `generate()`.
- Added typed exception aliases (`LLMUnavailableError` tuple +
  per-type names: `LLMServiceUnavailableError`, `LLMAPIConnectionError`,
  `LLMNotFoundError`, `LLMRateLimitError`, `LLMAuthenticationError`).
- Migrated 4 router sites + 22 service/runtime sites off direct
  `litellm.acompletion`. Routers no longer import `litellm`.
- Test stubs (`MockLLMService`, `CapturingLLMService`) gained
  `complete`/`stream_messages`. 11 test files redirected to patch the
  single gateway site (`app.services.llm.litellm.acompletion`).
- After: only `services/llm.py` and `services/context_packer.py`
  (`token_counter` only -- pure tokenizer, no inference) import litellm.
- Verified: ruff clean, 1548 passed / 3 skipped pytest.

### 3. DocumentReader.tsx split (audit #10)

#### Phase A -- subcomponents extracted -- `cbb5d94` + fix-up `3dd5a97`
- `DocumentReader.tsx`: 3,335 -> 1,545 lines (-54%).
- 9 new sibling files under `frontend/src/components/reader/`:
  `GlossaryPanel`, `ChapterGoalsPanel` (+ `ChapterProgressRing`),
  `SummaryPanel`, `HighlightsPanel` (+ `SectionPreviewWithHighlights`),
  `MediaPlayers` (Audio + Video), `PredictPanel`, `ResumeBanner`,
  `InDocSearchBar`, `SectionListItem` (+ `NoteEditor` + section helpers),
  `mediaUtils` (`parseAudioStartTime`, `formatMmSs`).
- Fix-up commit corrected imports against the strict `tsconfig.app.json`
  (the default `tsc --noEmit` was using a permissive config and missed
  the unused/missing imports).

#### Phase B -- custom hooks extracted -- `236bc46`
- `DocumentReader.tsx`: 1,545 -> 1,290 lines (-61% from original 3,335).
- 6 new hook files under `frontend/src/components/reader/hooks/`:
  - `useReadingProgress` -- IntersectionObserver + 3s dwell + library invalidation
  - `useSelectionWorkflow` -- 9 dialog-state fields + 5 SelectionActionBar handlers
  - `useSectionListCollapse` -- collapsedParents + sectionTree memo + isSectionHidden
  - `useReaderTabs` -- leftTab + visited flags + format-mismatch correction
  - `useReaderHistory` -- in-doc navigation stack with consumer-supplied navigateTo
  - `useReaderKeyboardShortcuts` -- Cmd+[ back, Cmd+F open search, Esc close
- Hook density inside `DocumentReaderBase` dropped ~101 -> 65 calls.

### 4. .gitignore hygiene -- `04297a6`
- Excluded `backend/app.db` (local SQLite), personal `DATA/` subdirs
  (`code/`, `conversations/`, `notes/`, `papers/`, `books/frankenstein.txt`),
  and `.claude/` local config.

## TODOs

In priority order from the read-only audit:

### Next: audit #1 -- split `FlashcardService`
- File: `backend/app/services/flashcard.py` (2,034 lines).
- One class spans lines 907-2029 (~1,120 lines) with 10 large `async`
  methods: `search`, `generate`, `generate_from_notes/collection/gaps/`
  `feynman_gaps/graph`, `generate_technical`, `generate_cloze`.
- Each `generate_*` is a near-clone of the others.
- Refactor approach: split into `FlashcardSearchService` +
  `FlashcardGenerator` strategy family (one strategy per source), with
  shared `_build_prompt` / `_parse_llm_response` helpers already
  module-level (lines 446-712).
- Likely also drains several `noqa: PLC0415` inline imports (current
  count: 299 across `backend/app/`).

### Then: audit #2 -- split god routers
- `routers/study.py` (2,429 lines, 25 endpoints, 77 top-level defs):
  schemas (lines 117-445) move to `schemas/study.py`; helpers
  (`_compute_gaps:185`, `_compute_section_heatmap:356`,
  `_build_session_plan:441`) into existing `services/study_session_service.py`.
- Same problem in `documents.py:1714`, `notes.py:1377`, `flashcards.py:1002`.
- Mechanical but touches many files -- do it once `services/` is cleaner so
  this is not just shuffling.

### Lower priority items from audit (not yet started)

- **#5: God class -- `KuzuService`** (`backend/app/services/graph.py:60`).
  41 methods on one class, file is 1,758 lines. Cleanly splits into
  `KuzuPrereqRepo`, `KuzuConceptRepo`, `KuzuViewRepo` over a shared
  `KuzuConnection`.
- **#6: God workflow -- `runtime/chat_graph.py`** (1,871 lines, 34 node fns).
  Refactor: one file per node group under `runtime/chat_nodes/` with a
  thin `chat_graph.py` that just wires them.
- **#7: 299 `noqa: PLC0415` inline imports** -- signals circular deps and
  routers/services importing each other lazily. Real fix: thinner
  services, dependency-injected via `Depends()`, no service-to-service
  backreferences. Will partly fall out of #1 + #2.
- **#8: "fetch + check + 404" boilerplate (115 sites)** -- extract
  `repo.get_or_404(model, id, name)` helpers.
- **#9: 263 direct `session.execute/commit/add/delete` in routers** --
  push into per-entity Repo modules (`repos/`). No `repos/` layer exists
  yet, only `services/`.
- **#11: God pages** -- `pages/Study.tsx` (2,190), `pages/Notes.tsx` (1,318),
  `pages/Monitoring.tsx` (1,313), `pages/Chat.tsx` (1,291). Same
  Phase A pattern as DocumentReader: extract inline subcomponents into
  siblings.
- **#12: 263 direct `fetch()` calls outside `frontend/src/lib/`** --
  the api-module pattern (`*Api.ts`) is followed inconsistently. Pick one
  and migrate so error/auth handling stops being duplicated.

## Branch-state notes

- `feat/refac-1-luminary` has ~136 uncommitted items at the time of this
  document (47 modified, 88 untracked). Those are pre-existing
  in-progress work on chat_sessions, engagement, pomodoro, evals,
  frontend updates, and `docs/` (which is untracked entirely despite
  being the project's "system of record" per `CLAUDE.md`). They are NOT
  part of the refactor commits above and need separate triage by the
  branch owner.

- Pre-existing test failures unrelated to the refactor:
  - Frontend `vitest`: 11 failures in `pdfHighlightOverlay.test.ts` and
    `pdfTocUtils.test.ts` (both pre-date the refactor; same failures
    with refactor stashed).
  - Backend `pytest`: `test_pomodoro_service::test_stats_only_completed_count_total`
    is date-flaky (`assert 1 == 2` for `today_count`).
  - Backend `tsc`: `src/components/evals/AblationsTab.tsx` (recharts type)
    and `src/pages/Admin.tsx` (unused `Legend` import) -- pre-existing on
    this branch.

## Refactor commit log

```
236bc46 refactor(reader): split DocumentReaderBase into custom hooks (Phase B)
3dd5a97 refactor(reader): fix Phase A imports for strict tsc
cbb5d94 refactor(reader): split DocumentReader.tsx (Phase A)
74ef6ed refactor(llm): centralize all completions through services/llm.py
04297a6 chore(gitignore): exclude local DB, personal corpus, .claude config
```
