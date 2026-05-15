# Refactor TODOs (branch: feat/refac-1-luminary)

Per the user's preference, this file tracks **only what's still pending**.
Completed phases live in `git log` (search `refactor:` / `chore:` since
the branch root). Design principles distilled from completed audits are
at the bottom.

## Status snapshot (2026-05-15)

**Done:** #1 FlashcardService, #2 god-router schemas/helpers, #5 KuzuService
(6 phases), #6 chat_graph (9 phases), #7 PLC0415 sweep (299→<100, target met),
#8 get_or_404 helper, #9 repos+services Phases 1-11 (Clip/Annotation/Collection/
Tag/Note/Flashcard/Document/Study repos + DocumentDeletionService +
TagMergeService + small-router sweep), #11 god pages Phases A-G (Study, Viz,
Notes, Monitoring, Chat, Learning, Teachback), #12 fetch standardization
(248→8 raw fetches + eslint rule), #13 ingestion split (7 phases), **#15
OpenAPI→TS codegen + frontend type alignment**.

## Still pending

### #9 -- session-ops residual (DONE 2026-05-15)
All remaining inline `session.execute/add/commit/delete` calls in routers
now have a rationale comment. 11 router files annotated: code_executor,
summarize, images, search, chat_meta, flashcards, notes, collections,
tags, documents, study. Patterns documented:
- Custom projections / bespoke aggregations no repo method covers
- Atomic multi-table writes (note + FTS + tag index + source pivot)
- Shared session with get_or_404 guard
- Ingestion document row before background job
- Service delegation where session is passed through (delete cascade)
- Hop-by-hop join chains with 404 at each step
- Dedicated isolated sessions (XP background tasks)

New `session.execute(` in routers should be caught by a CI grep (not yet wired).

### #11 -- god-page holdouts (intentional)
`components/reader/DocumentReader.tsx` (~1,290) and
`components/NoteReaderSheet.tsx` (~1,039) stay per design principle 6
(tightly-coupled orchestrators). Revisit only if the orchestration
genuinely changes shape.

### #14 -- mid-size services (exploratory, no commitment)
`services/summarizer.py` (696) remains. The pattern is now established:
split into `<service>.py` (orchestrator) + `<service>_strategies.py`
(swappable bits), re-exporting moved symbols from the original module so
all test imports and patch targets work unchanged.

**retriever.py done (2026-05-15)**: 874 → 469 lines. Strategy helpers
(`_round_robin`, `_diversify`, `_sanitize_fts_query`, `_expand_context`,
`_CrossEncoderReranker`/`_get_reranker`, `_hyde_expand`, `_graph_expand`)
extracted to `retriever_strategies.py` (431 lines). `_rerank_candidates`
stays in `retriever.py` so `patch("app.services.retriever._get_reranker")`
keeps intercepting its call to `_get_reranker`. Moved symbols re-exported
from `retriever.py` so all test imports and patch targets work unchanged.
43 retriever tests pass.

**feynman_service.py done (2026-05-15)**: 636 → 496 lines. Prompt
templates, `_SECTION_CONTEXT_CHAR_LIMIT`, `_fire_and_forget`, and all
five parsers (`_parse_gaps`, `_parse_rubric`, `_parse_key_points`,
`_strip_key_points_block`, `_strip_gaps_block`) extracted to
`feynman_strategies.py` (166 lines). All symbols re-imported into
`feynman_service.py` so tests that directly import parsers from there
continue to work. 14 feynman tests pass.

### #15 -- TypeScript codegen follow-through (DONE)
Initial codegen landed earlier; in 2026-05-15 the frontend was swept
to alias generated types wherever the shapes align. ~80 inline
re-declarations across 17 files now read
`components["schemas"]["FooResponse"]`. Twelve shapes were
deliberately kept inline -- always with a comment explaining why --
in the following categories:

- **UI-only state**: ChatMessage, AnyCardData, SectionState<T>,
  CollectionTreeNode, SummaryTabDef etc.
- **Cross-page minimal subsets**: DocListItem (Study/Chat/Viz),
  DocumentItem (Notes/NoteEditorDialog/NotesReaderPanel/GapDetectDialog/
  NoteReaderSheet), DocItem (GoalCreateDialog), Document (Admin/
  Monitoring 4-field projection of DocumentListItem).
- **Backend returns `dict`**: /engagement/* family (XPHistoryItem,
  XPSummary, StreakData, FocusStats, Achievement),
  /collections/{id}/flashcards/generate (CollectionGenerateResponse),
  /chat_meta auto-collection lookup (AutoCollection),
  /search internal (NoteStub).
- **Narrower literal unions cascade through indexed maps**:
  WebReferenceItem.source_quality and WebRef.source_quality
  (SourceQuality literal union drives QUALITY_LABEL records);
  AnnotationItem.color (Omit + intersect kept locally on the reader
  side -- the highlight-color UI exhaustively switches over the four
  literals); library/types.ts DocumentListItem.content_type +
  learning_status (ContentType / LearningStatus unions used by
  CONTENT_TYPE_ICONS / CONTENT_TYPE_BADGE records).
- **SSE event payloads**: QaStreamRequest, Citation, WebSource,
  TransparencyInfo (not exposed via REST so not in OpenAPI).

Acceptance: zero remaining schema-mirror re-declarations. The only
inline `interface FooResponse` blocks left in `src/{pages,components}`
are the four kept-local categories above, each with an inline
comment that next time can be checked against without re-reading the
schema.

**Operational note recorded during this pass:** `npx tsc --noEmit`
from `frontend/` does not validate the app project's references --
always use `npx tsc -p tsconfig.app.json --noEmit` to catch missing
fields (e.g. EvalRunListItem vs EvalRunResponse). This caught two
real divergences (Monitoring EvalRun, Notes section_id) that the
bare tsc invocation reported as clean.

## Design principles (apply to every remaining phase)

Distilled from audits #1, #2, #5, #6, #8, #9, #11, #12, #13. Read
before starting any extraction.

1. **Re-export, don't break.** When code moves, keep the old name
   importable from its original home (`# noqa: F401`).
2. **Re-exports are name bindings, not call sites.** After a move,
   update `mock.patch("old.X")` -> `mock.patch("new.X")` or the patch
   silently no-ops.
3. **Indirect through the original module for swappable singletons.**
   `get_llm_service`, `get_retriever`, `get_graph_service`, etc. should
   be reached via `from app.services import X as _X_module` and called
   as `_X_module.get_Y()` at call time -- never `from app.services.X
   import get_Y` (that binds the symbol locally and silently breaks
   `patch("app.services.X.get_Y")`). The PLC0415 sweep (audit #7) hit
   this several times; if you promote a lazy import to top-level and
   tests patch its source module, switch to the module-indirect form.
4. **Schemas + helpers + body, in that order.** God-router playbook:
   (a) lift Pydantic schemas to `app/schemas/<entity>.py`;
   (b) lift pure helpers to `app/services/<entity>_service.py`;
   (c) only then split the body.
5. **Repos own session ops, services own logic, routers own HTTP.**
   When a router keeps `session.execute` after a repo lands, document
   why (transactional, bespoke join shape, etc.).
6. **Don't fight tightly-coupled orchestrators.** Helpers that flush
   mid-transaction and fan out across stores (`_apply_note_update`,
   `delete_document`, `DocumentReader.tsx`) stay where they are with a
   comment explaining why.
7. **Measure before and after.** Every phase commit records line counts
   (`1,924 -> 1,565`). Makes regressions visible.
8. **Audit `# noqa: PLC0415` after each extraction.** Lazy imports
   were circular-dep workarounds; promote and delete the noqa when the
   cycle is broken. Count is a primary health metric.
9. **When you build a facade, pass-through with kwargs.** Audit #5
   left two facade methods (`KuzuService.upsert_diagram_node`,
   `add_diagram_edge`) passing args positionally to the underlying
   repo where the parameter order had diverged. The mismatch was
   masked by a `try/except` in the caller -- silent data corruption.
   For thin delegations, prefer `return self._repo.method(**kwargs)`
   so any signature drift surfaces as a TypeError at test time, not
   as wrong data.

## Pre-existing test failures (do not chase unless asked)

- Frontend vitest: 11 failures in `pdfHighlightOverlay.test.ts` and
  `pdfTocUtils.test.ts` (predate this branch).
- Backend pytest: `test_pomodoro_service::test_stats_only_completed_count_total`
  is date-flaky.
- Frontend tsc: `evals/AblationsTab.tsx` (recharts type) and
  `pages/Admin.tsx` (unused `Legend` import).
