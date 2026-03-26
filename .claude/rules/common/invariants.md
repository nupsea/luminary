---
description: Luminary hard invariants -- always loaded. Violations block passes=true. These rules have each been learned from a real incident or design decision.
---

# Luminary Invariants

These are non-negotiable. Each one exists because its violation caused a real bug or regression.

## Async / Concurrency

**I-1. Never share AsyncSession across `asyncio.gather` tasks.**
Each concurrent task needs its own session or a `Semaphore(1)` serialiser. SQLAlchemy AsyncSession is not safe for concurrent use.

**I-2. Wrap all synchronous LanceDB calls with `asyncio.to_thread`.**
LanceDB is synchronous. Calling it directly in an async function blocks the event loop.

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

**I-9. Note and chunk vectors are 1024-dimensional (bge-m3 output).**
The LanceDB schema must declare `pa.list_(pa.float32(), 1024)`. Any table with 384-dim is from a pre-S170 bug and must be dropped and recreated.

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
