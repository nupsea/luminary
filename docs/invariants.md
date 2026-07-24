---
description: Luminary hard invariants -- always loaded. Violations block passes=true. These rules have each been learned from a real incident or design decision.
---

# Luminary Invariants

These are non-negotiable. Each one exists because its violation caused a real bug or regression.

## Async / Concurrency

**I-1. Never share AsyncSession across `asyncio.gather` tasks.**
Each concurrent task needs its own session or a `Semaphore(1)` serialiser. SQLAlchemy AsyncSession is not safe for concurrent use.

**I-2. Wrap all synchronous LanceDB *and Kuzu* calls with `asyncio.to_thread`.**
Both are synchronous. Calling either directly in an async function blocks the event loop -- and because the server runs a single worker, it stalls *every* concurrent request, not just the slow one. Measured: a 2ms `/tags/graph` took 8.5s sitting behind one all-library `/graph` traversal, which is why the Map's Tags view appeared to hang. Kuzu is safe to call from a worker thread: `ThreadSafeKuzuConnection` already serializes every `execute()` under an RLock.

**I-3. Always guard Kuzu `get_next()` with `has_next()`.**
`get_next()` raises if no rows exist. Every Kuzu result iteration must call `has_next()` first.

## FTS5 / SQLite

**I-4. Do not use `WHERE unindexed_col = :val` on FTS5 virtual tables.**
UNINDEXED columns are unreliable for equality filtering when the table is large. Query the shadow content table directly: `notes_fts_content WHERE c1 = :nid` (columns c0, c1, c2 match CREATE VIRTUAL TABLE order). Deletion: `DELETE FROM notes_fts WHERE rowid = :rowid` (rowid-based delete always works).

## Imports

**I-5. Never import at module level inside a service if it creates a circular dependency.**
Use lazy imports inside the method body: `from app.runtime.X import fn  # noqa: PLC0415`. Patch target is then `app.runtime.X.fn`, not the call-site import.

**I-6. Import `get_settings()` at module level in services.**
Never suppress `get_settings()` exceptions with bare `except`. Never lazy-import settings -- it makes the patch target unpredictable in tests.

## LLM / SSE

**I-7. Persist rows before LLM calls in SSE generators; add explicit rollback on error.**
Implicit rollback on session close is insufficient after a generator exception. Add explicit `await session.rollback()` in the error handler.

**I-8. The `done` SSE event payload contains the clean `answer` field.**
The frontend must replace `msg.text` with `payload.answer` on the done event. Streamed tokens include citation JSON fragments -- never leave raw accumulated tokens as the final displayed text.

## Vector Dimensions

**I-9. Note and chunk vectors are 384-dimensional (bge-small-en-v1.5 output).**
The LanceDB schema must declare `pa.list_(pa.float32(), 384)`. Notes and chunks share one embedder and one vector space, so a note vector is directly comparable to a chunk vector. Any table declaring a different dimension is a bug.

## Frontend

**I-10. Every frontend feature must have loading, error, and empty states.**
No blank panels. Loading = skeleton (not spinner blocking the page). Error = inline message per section. Empty = explicit "No X yet" message.

**I-11. Cross-tab navigation uses the `luminary:navigate` DOM event and Zustand store.**
Never use URL hacks or React Router state for cross-tab navigation. Dispatch `new CustomEvent('luminary:navigate', { detail: { tab, filter } })` and handle it in App.tsx.

**I-12. Never use MarkdownRenderer inline in list/table cells.**
Block-level elements (h1, ul) inside a `<td>` break layout. Use `stripMarkdown()` from `src/lib/utils.ts` for single-line text previews.

## Quality Gates

**I-13. Quality gates run in order: ruff -> pytest -> tsc.**
Fix ruff before running pytest (lint errors mask test errors). Never set `passes=true` before all three pass.

**I-14. `passes=true` requires smoke exit 0 and reviewer returning no Critical items.**
Tests passing is necessary but not sufficient. The smoke test verifies the backend contract the UI depends on.

## Packages

**I-15. Use `uv` only -- never `pip` or `poetry`.**
The lockfile is `uv.lock`. Adding packages: `uv add <package>`. Never run `pip install` directly.

## Privacy & Local-First

**I-16. Prioritize local LLM (Ollama) and local search (none/duckduckgo) by default.**
Never introduce a new external API dependency (e.g., Tavily, OpenAI) without providing a local-first or privacy-preserving alternative.

**I-17. Never log or transmit user content (notes, documents) to external telemetry.**
Arize Phoenix and Langfuse must be configured for local use only. Telemetry is for performance metrics and trace structure, not for content mirroring.

**I-18. Explicitly disable telemetry in third-party libraries (e.g., LiteLLM, LangChain).**
Check and disable any "phone home" features in libraries that handle user prompts.

## Concepts & Knowledge Layer

**I-19. Mastery is a stored scalar on the concept row -- never recomputed by text match, never on documents or collections.**
The legacy `chunk.text ILIKE '%name%'` mastery computation is removed. Mastery is written by the assessment pipeline (Study Events) to `concepts.mastery`. Collection/goal numbers are computed rollups, never stored as truth. See `docs/concepts.md`.

**I-20. The concept vector is derived and never a retrieval primary.**
A concept's LanceDB vector (`concept_vectors_v1`) is the 384-dim centroid of its evidence-chunk embeddings, in **chunk space** (bge-small-en-v1.5; chunks, notes, and concepts are all 384-dim in one shared space). Recomputed when evidence changes. Use it only for concept-to-concept and material-to-concept similarity (linking, dedup, candidate seeding, scope resolution). Chunk vectors + FTS5 + graph (RRF) remain the RAG backbone.

**I-21. OKF is a projection, never a transport and never a source of truth.**
LiteLLM carries bytes; OKF carries portable knowledge -- never couple them. OKF files are regenerated from SQLite + Kuzu. A user edit to an OKF file re-enters the system only as an `override` (re-applied after re-parse), exactly like a graph rename/merge. See `docs/okf.md`.

**I-22. A rejected or edited graph element must not reappear after re-parse.**
Re-parse produces fresh proposals, then `applyOverrides()` re-applies every user decision on top. Rejected concepts/edges and dismissed gaps stay gone (hidden, not deleted). Overrides survive re-parsing -- they are the user's permanent voice over Lumen's guesses.

**I-23. Schema changes are Alembic revisions. The `ALTER TABLE` list in `db_init.py` is frozen.**
`models.py` is the source of truth; `make db-revision m="..."` generates the migration and the server applies it on boot. `db_init.create_all_tables()` is a one-time bridge that lifts pre-Alembic databases to the baseline -- never add to it. Generate revisions ONLY via `make db-revision` (it diffs against a throwaway database): pointed at a long-lived one, autogenerate emits `drop_table()` for real user tables. `tests/test_schema_drift.py` fails CI when models and migrations disagree.

**I-24. Never add code that clears a Kuzu lock or kills a process holding one.**
Kuzu takes an exclusive OS-level file lock that the kernel releases the instant the holder dies (verified against SIGKILL; no lock artifacts on disk). A stale lock therefore cannot exist, so any "release the stale lock" logic can only ever kill a LIVE process mid-write -- which is how a graph database gets corrupted. A held lock means a real second process (another server, or `make concepts`): surface it and let the user stop it. A hand-rolled lockfile is strictly worse than Kuzu's own, because ours *can* go stale.

**I-25. Scope decides WHERE to look, never WHAT was asked.**
`scope='all'|'single'` must not influence intent classification. Telling the classifier to prefer `summary` when scope is the whole library made every bare topic ("Apache Iceberg") a summary request under All-documents while the identical query returned `factual` under a single document. Any node that cannot serve its intent falls through to retrieval (`return {"intent": "factual"}`, which `_route_after_strategy` sends to `search_node`) rather than answering with a placeholder -- a question always gets a real answer.
