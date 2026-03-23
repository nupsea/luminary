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

---

## Commands

- All uv/pytest commands run from the absolute path `/Users/sethurama/DEV/LM/learning-mate/backend` — never `cd backend &&` prefix in subprocess calls
- Run tests: `uv run pytest` (from backend dir)
- Run lint: `uv run ruff check .` (from backend dir)

---

## AsyncIO Patterns

- `asyncio.gather` with Semaphore: wrap each coro in `async with semaphore:` inside an inner async fn, then `gather(*[inner(i) for i in units])`
- `litellm.ServiceUnavailableError` must be caught at the `asyncio.gather` call site — catching inside each unit coro doesn't propagate through gather; use try/except around gather to catch and return 0

---

## Import Patterns

- Circular imports: use lazy import inside the method body — `from app.runtime.chat_graph import get_chat_graph  # noqa: PLC0415`
- Lazy import for cross-service calls: `from app.services.summarizer import get_summarization_service  # noqa: PLC0415` inside the method body
- qa.py helpers (_split_response, _build_context, etc.) stay at module level — chat_graph.py imports them directly from app.services.qa

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

---

## Summarization

- Fast path assertion: exactly 3 generate calls (one per mode); slow path with 3×3000-token chunks: >3 calls (map-reduce + modes)
- Lazy import for SummarizationService inside section_summarizer.py to avoid circular import

---

## Context Packer

- LCS dedup uses DP with row-rolling optimization (_LCS_CHAR_LIMIT=300 for O(n²) performance)
- dedup_ratio=1.0 disables deduplication (always include all chunks within budget)

---

## Frontend Rendering Consistency

- List/table views must NOT use MarkdownRenderer inline — block-level elements (h1, ul) inside a td break layout. Use a stripMarkdown() utility to strip heading markers, bold, italic, blockquote, and backtick symbols for single-line text previews. Card and detail views should use the full renderer.
- stripMarkdown() is a pure function in src/lib/utils.ts. It strips `#`, `**`, `__`, `*`, `_`, `>` markers from preview text without rendering HTML.
- Vite dev server does NOT hot-reload tailwind.config.cjs changes. Restart `npm run dev` after any config change. `npm run build` always produces correct output.

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
