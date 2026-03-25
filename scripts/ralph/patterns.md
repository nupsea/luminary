# Ralph Codebase Patterns

Stable patterns accumulated across stories. Read before implementing any story.
Update this file (in-place) when new patterns are discovered — do NOT append chronologically.

---

## Settings / Config

- LLM model field: `get_settings().LITELLM_DEFAULT_MODEL` (not `default_model`)
- Ollama URL field: `get_settings().OLLAMA_URL`

---

## Test Fixtures

- DB isolation: `make_engine("sqlite+aiosqlite:///:memory:")` + `create_all_tables` + monkeypatch `db_module._engine` and `db_module._session_factory`
- Mock LLM at graph level, not at litellm level: `patch("app.runtime.chat_graph.get_llm_service")`
- Mock get_llm_service (not litellm.acompletion directly) when testing SummarizationService.pregenerate() — avoids tracing/telemetry complications
- Lazy import patch location: patch at source module, not destination — e.g. `app.services.graph.get_graph_service` not `app.runtime.chat_graph.get_graph_service`. The lazy import (`from app.services.X import fn`) at call time fetches `fn` from `sys.modules['app.services.X']`, so patching the attribute on the source module is always correct regardless of where the call site lives.
- CO_OCCURS edge weight in Kuzu is a raw co-occurrence count (1, 2, ..., N) -- NOT a probability. Normalise before exposing as "confidence" to frontend: `max_weight = max((w for ...), default=1.0) or 1.0; confidence = round(w / max_weight, 4)`. This prevents frontend percentage displays like "1200%".
- mock at graph level with `patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph)` where `mock_graph.ainvoke` is AsyncMock
- Performance tests: use `LUMINARY_PERF_TESTS` env guard + `pytest.mark.skipif`
- Book fixture is "The Odyssey" (not "The Iliad") — use Odyssey-specific entities for relational tests
- **AsyncClient (httpx) test pattern**: `TestClient(app)` as a context manager triggers FastAPI lifespan (startup events). `AsyncClient(transport=ASGITransport(app=app))` does NOT trigger lifespan. Use the `test_db` fixture to initialize the DB when writing async tests with AsyncClient.
- **asyncio.to_thread mocking**: use `AsyncMock(return_value=expected_value)`, NOT `MagicMock(side_effect=lambda fn, *args: coroutine_obj)`. The MagicMock returns the coroutine object itself (unwraped), so `result = await asyncio.to_thread(...)` sees a coroutine object as the value, not the awaited result. AsyncMock's `__call__` returns an awaitable that correctly resolves to `return_value`.

---

## Commands and Git

- All uv/pytest commands run from the absolute path `/Users/sethurama/DEV/LM/learning-mate/backend` — never `cd backend &&` prefix in subprocess calls
- Run tests: `uv run pytest` (from backend dir)
- Run lint: `uv run ruff check .` (from backend dir)
- **Force-add .gitignored story deliverables**: `docs/`, `scripts/ralph/`, and other execution/tracking files are in `.gitignore`. Use `git add -f <path>` when committing story changes to prd-v3.json, progress.txt, or docs/exec-plans/ files. Without `-f`, these files stay untracked and are not included in the commit.

---

## AsyncIO Patterns

- `asyncio.gather` with Semaphore: wrap each coro in `async with semaphore:` inside an inner async fn, then `gather(*[inner(i) for i in units])`
- `litellm.ServiceUnavailableError` must be caught at the `asyncio.gather` call site — catching inside each unit coro doesn't propagate through gather; use try/except around gather to catch and return 0
- `asyncio.run()` instead of `asyncio.get_event_loop().run_until_complete()` in test helpers — the latter is deprecated in Python 3.10+
- **Slow sync work outside locks**: when using `asyncio.to_thread` for slow work (e.g. GLiNER inference) before a Kuzu operation, run the slow work OUTSIDE the lock, acquire the lock only for the Kuzu writes. This prevents GIL contention from blocking other async tasks.
- **Kuzu thread-safety with asyncio.to_thread**: acquire `KuzuService._lock` (threading.Lock) in ALL callers of `_conn.execute()`, including existing direct callers in chat_graph and graph.py. Multiple concurrent `asyncio.to_thread` tasks can corrupt state without serialization.
- **In-memory TTL cache pattern**: Module-level `_cache: dict = {}` with keys "graph" → result, "ts" → float. Check freshness with `time.monotonic() - _cache["ts"] < TTL` (not `time.time()`, which can go backwards). Invalidate via `_cache.clear()`. Lazy-import the invalidation function in dependent modules to avoid circular imports.

---

## Import Patterns

- Circular imports: use lazy import inside the method body — `from app.runtime.chat_graph import get_chat_graph  # noqa: PLC0415`
- Lazy import for cross-service calls: `from app.services.summarizer import get_summarization_service  # noqa: PLC0415` inside the method body
- Cross-router lazy import for shared helpers: when two routers share a helper (e.g., `_sync_tag_index` in notes.py used by tags.py), lazy-import it inside the method body: `from app.routers.notes import _sync_tag_index  # noqa: PLC0415`. Avoids circular imports at module level between routers.
- qa.py helpers (_split_response, _build_context, etc.) stay at module level — chat_graph.py imports them directly from app.services.qa
- **Six-layer rule: services must not import from routers**: Routers are the API layer; services are the business logic layer. If a service needs to call a router-layer side effect (e.g. `_sync_tag_index`), move the side-effectful work to the router endpoint. The service returns validated/prepared data; the router endpoint executes the side effects. This preserves layering: Types → Config → Repo → Service → Runtime → API.

---

## LangGraph / Chat Graph

- search_node must NOT write a stub answer — if answer is non-empty, synthesize_node passes through and no_context flow breaks
- Conditional edges after strategy nodes: `_route_after_strategy` checks `intent='factual'` as fallthrough signal
- synthesize_node no-context check: not_found only when BOTH chunks and section_context are absent
- scope routing: `exploratory + scope=all` → `summary_node` (not `search_node`). Broad questions over the full library need per-document summary synthesis; chunk retrieval is biased toward the highest-similarity document.
- summary_node scope=all: fetches per-document executive summaries from `SummaryModel` (written during ingestion). Does NOT rely on `LibrarySummaryModel` (only written by the separate summarize-all endpoint). If no summaries exist, falls through to search with `intent='factual'`.
- comparative_node: uses `_decompose_comparison()` (LLM call) to extract `{sides: [N names], topic: str}`. Supports N-way (not just 2-way). Each side resolved to doc_ids via `_resolve_side_to_docs()` (Kuzu entity match + SQLite title search, unioned). Retrieval runs in parallel per side via `asyncio.gather`. Results interleaved round-robin.
- `_resolve_side_to_docs`: tries exact Kuzu entity match first, then partial match, then SQLite title contains. An entity appearing in multiple documents returns all of them. If scope_doc_ids set, intersects result.
- SSE streaming: the `done` event payload contains `answer` (clean prose, citation JSON stripped). The frontend MUST replace `msg.text` with `payload.answer` on the done event — never leave the accumulated streamed tokens as the final displayed text. Streamed tokens include citation JSON fragments that leaked before the break triggered.
- Log level policy: use `logger.info` at every graph node entry, routing decision, fallthrough, and final chunk count. Use `logger.debug` only for internal details. This makes the full query flow visible at INFO level without enabling DEBUG.

---

## Database Patterns

- SectionSummaryModel batch lookup by (document_id, heading) using SQLAlchemy OR conditions — avoids N+1 queries
- pack_context groups by section_id or section_heading fallback; sorts groups by max(relevance_score) desc
- To get the latest executive summary per document across all documents, use a subquery grouped by document_id with `func.max(created_at)`, then join back to SummaryModel and DocumentModel. Do not use DISTINCT ON (not supported by SQLite).
- **Shadow table sync pattern (_sync_tag_index)**: Call sync helpers synchronously within the same DB transaction as the primary write (NOT `asyncio.create_task`). Use `INSERT OR IGNORE` for idempotent shadow rows; use `ON CONFLICT(id) DO UPDATE SET count = count + 1` for atomic counter increments. SQLite serializes concurrent writes so no race condition exists with `asyncio.gather`.
- **Prefix-match hierarchical tag filter**: Match a tag and all children in one SQL query: `tag_full = :tag OR tag_full LIKE :tag || '/%'`. In SQLAlchemy: `NoteModel.id.in_(select(NoteTagIndexModel.note_id).where(or_(...)))`.
- **Backfill SQL for complex computed columns**: When backfill logic is too complex for pure SQLite (no REVERSE, no regex), set the column to a safe default (empty string) during migration. Recompute the correct value at write time via a helper function. Ensure queries never depend on the backfilled value being correct (e.g. use a different column like `tag_full` for filtering instead of `tag_parent`).
- **No session.refresh() when expire_on_commit=False**: after `await session.commit()`, do NOT call `session.refresh(instance)`. When expire_on_commit=False, all attributes set in Python before commit are preserved. The refresh creates an extra await point where background tasks (asyncio.to_thread GLiNER) can run and corrupt session state under load.
- **Bulk one-to-many loading pattern**: after fetching a list of rows, do a single query for all IDs to load related junction table rows. Build a `dict[id, list[related_ids]]` map, then pass to response constructor. Prevents N+1 queries when building responses with one-to-many relationships (e.g., notes with their collection_ids).
- **Self-join co-occurrence pattern**: To find undirected pairs of related entities, self-join on their common relationship: `JOIN table b ON a.foreign_key = b.foreign_key AND a.id < b.id` (string comparison ensures each pair appears once, no self-loops). Apply HAVING COUNT(*) >= min_weight to filter weak edges. Example: `a.tag_full < b.tag_full` for tag co-occurrence on shared notes.

---

## Summarization

- Fast path assertion: exactly 3 generate calls (one per mode); slow path with 3×3000-token chunks: >3 calls (map-reduce + modes)
- Lazy import for SummarizationService inside section_summarizer.py to avoid circular import

---

## Context Packer

- LCS dedup uses DP with row-rolling optimization (_LCS_CHAR_LIMIT=300 for O(n²) performance)
- dedup_ratio=1.0 disables deduplication (always include all chunks within budget)

---

## LanceDB / Vectors

- All LanceDB calls are synchronous. In async context: `await asyncio.to_thread(table.search(...).to_pandas)`
- Vector dimension: 1024 (bge-m3). Any table with 384-dim is stale -- drop and recreate.
- **LanceDB schema introspection**: use `tbl.schema.field("vector").type.list_size` to read the FixedSizeList dimension. Wrap in try/except — if the field is missing or the attribute doesn't exist, log a warning and proceed with safe default (assume 1024).
- **LanceDB drop+recreate**: use `self._db.drop_table(TABLE_NAME)` via the connection object, NOT `tbl.drop()`. Then `self._db.create_table(TABLE_NAME, schema=NEW_SCHEMA)`. Use this when a table's schema (e.g. vector dimension) needs to change.

---

## FastAPI Patterns

- **Admin key header dependency**: capture `X-Admin-Key` with `Header(default=None)` parameter; validate with `if settings.ADMIN_KEY and x_admin_key != settings.ADMIN_KEY: raise HTTPException(403)`. Allows unauthenticated access if `ADMIN_KEY` is not set.
- **Fire-and-forget background task in router**: use `asyncio.create_task` to spawn the task; inside the task body, create a fresh AsyncSession with `async with get_session_factory()()`. Never reuse the request-scoped session (it closes after handler returns, leaving the task with a closed session).
- **Dynamic path parameter route ordering**: ALL static-path routes (POST /merge, GET /search, GET /flashcards) MUST be registered BEFORE any /{param} route. If /{param} is registered first, GET /search matches with param="search" and returns 404. In tags.py: POST /tags/merge before GET|PUT|DELETE /tags/{tag_id}.
- **Pydantic model_fields_set for nullable PATCH fields**: use `if "field_name" in req.model_fields_set: model.field = req.field` to distinguish "not supplied" from "explicitly set to null". The old pattern `if req.field is not None` silently ignores explicit null (e.g. clearing parent_tag). Apply this whenever a PUT/PATCH endpoint needs to clear a value back to null.

---

## Frontend Rendering Consistency

- List/table views must NOT use MarkdownRenderer inline — block-level elements (h1, ul) inside a td break layout. Use a stripMarkdown() utility to strip heading markers, bold, italic, blockquote, and backtick symbols for single-line text previews. Card and detail views should use the full renderer.
- stripMarkdown() is a pure function in src/lib/utils.ts. It strips `#`, `**`, `__`, `*`, `_`, `>` markers from preview text without rendering HTML.
- Vite dev server does NOT hot-reload tailwind.config.cjs changes. Restart `npm run dev` after any config change. `npm run build` always produces correct output.
- **Vitest node environment + Zustand store**: when vitest environment is "node", do NOT import React components that transitively depend on Zustand stores (localStorage is read at module load). Solution: extract pure logic functions to a separate utility file with no React/store imports (e.g., `src/lib/collectionUtils.ts`, `src/lib/tagUtils.ts`), and test only from that utility. Component test files must import from the utility, not the component.
- **Hierarchical API response schema**: when a child record displays or initializes UI based on parent relationship, include the parent reference in the nested child response (e.g., `parent_tag: str | None` in TagTreeItem) even though it's redundant with tree structure. Without it, the UI cannot pre-select the current parent in a dropdown.
- **HTML5 drag-and-drop**: add `draggable` attribute to draggable element, `onDragStart={(e) => e.dataTransfer.setData("text/plain", id)}` to set data. Drop target: `onDragOver={(e) => e.preventDefault()}` + `onDrop={(e) => e.dataTransfer.getData("text/plain")}`. No DnD library needed.
- **New UI mode guards in existing tabs**: when adding a fundamentally different viewMode (e.g., "tags" to Viz.tsx without document scope), guard ALL document-specific UI controls, state booleans, and queries with `viewMode !== "new_mode"` checks. Easy to miss: showEmpty/showAllHidden/isLoading/isError in state overlays. List all guarded items in a comment to catch inconsistencies.

---

## Post-Save Async Flows (TanStack Query + Ollama)

- **All entry points must be covered**: a feature that fires after save (e.g. auto-tagging) can be triggered from multiple UI surfaces (create form, edit dialog). ACs must name every entry point explicitly. Testing only one surface and marking passes:true means the feature is partially broken.
- **TanStack Query onSuccess must be synchronous**: In v5, onSuccess callbacks are not awaited. An `async onSuccess` with `await` inside creates a Promise that TanStack Query discards. Post-mutation async logic (like firing a secondary fetch) must use `useEffect` watching `mutation.isSuccess`, or be chained inside `mutationFn` itself.
- **Silent Ollama fallback looks identical to a broken feature**: when a best-effort LLM call returns [] because Ollama is offline, the UI must show explicit feedback ("No suggestions available" or "Ollama offline"). Auto-closing with no message is indistinguishable from the feature never running.
- **Dialog close after save must be explicit**: auto-closing a dialog immediately after save prevents any post-save feedback (suggestions, status messages) from being visible. Always transition to a "Saved" state and let the user close with Done.
- **AbortController on unmount**: in-flight fetch requests inside a dialog must be cancelled when the dialog closes (onOpenChange fires with open=false). Store the AbortController in a ref; call abort() in the cleanup. Prevents React "setState on unmounted component" warnings.

---

## AC Verification Completeness

- ACs must describe the full observable user flow, not just that an endpoint returns the right shape. "POST /notes/{id}/suggest-tags returns tags" passes even if the UI never shows them.
- For any story where a feature fires asynchronously after a user action: the AC must name the trigger surface, the visible loading state, the success state, and the offline/error state. All four must be verified before passes:true.
