---
description: Python-specific Luminary patterns. Loaded when working on Python files. Mirrors scripts/ralph/patterns.md but structured for Claude Code rule injection.
globs: ["backend/**/*.py"]
---

# Python Patterns (Backend)

These are accumulated from real stories. Read before writing any backend code.

## Settings / Config

- LLM model field: `get_settings().LITELLM_DEFAULT_MODEL` (not `default_model`)
- Ollama URL field: `get_settings().OLLAMA_URL`
- Import `get_settings()` at module level. Never lazy-import it in method bodies.

## SQLAlchemy / Database

- DB isolation in tests: `make_engine("sqlite+aiosqlite:///:memory:")` + `create_all_tables` + monkeypatch `db_module._engine` and `db_module._session_factory`
- Concurrent tasks: never `asyncio.gather` with a shared AsyncSession. Use `Semaphore(1)` or give each task its own session.
- Batch lookup by composite key: use SQLAlchemy OR conditions -- avoids N+1 queries
- To get the latest row per group in SQLite: use a subquery grouped by document_id with `func.max(created_at)`, then join back. Do not use DISTINCT ON (not supported by SQLite).
- `StaticPool` required for in-memory SQLite in concurrent tests (`create_engine(..., poolclass=StaticPool)`)

## FTS5

- UNINDEXED column equality filtering is unreliable at scale. Query shadow content table: `notes_fts_content WHERE c1 = :nid` (c0, c1, c2 = column order from CREATE VIRTUAL TABLE)
- Deletion: `DELETE FROM notes_fts WHERE rowid = :rowid` -- rowid-based delete is always reliable
- This pattern applies to ALL FTS5 tables with UNINDEXED columns

## LanceDB / Vectors

- All LanceDB calls are synchronous. In async context: `await asyncio.to_thread(table.search(...).to_pandas)`
- Vector dimension: 1024 (bge-m3). Any table with 384-dim is stale -- drop and recreate.
- Note vector table: `note_vectors_v2`. Chunk vector table: `chunk_vectors`.

## Kuzu / Graph

- `get_next()` raises if no rows. Always guard: `if result.has_next(): row = result.get_next()`
- CO_OCCURS edge weight is a raw count (1..N), NOT a probability. Normalise before sending to frontend: `confidence = round(w / max_weight, 4)`
- Kuzu connection is not thread-safe. Do not share `_conn` across async tasks.

## LangGraph / Chat Graph

- Topology (after S81): `classify -> route -> [summary|graph|comparative|search] -> synthesize -> confidence_gate -> [END | augment -> synthesize -> confidence_gate -> END]`
- `search_node` must NOT write a stub answer -- non-empty answer causes synthesize to pass through and breaks no-context flow
- Mock at graph level in tests: `patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph)` where `mock_graph.ainvoke` is AsyncMock
- `scope=all + exploratory` routes to `summary_node` (not search_node) -- broad questions need per-document executive summaries

## LiteLLM / SSE

- Catch `litellm.ServiceUnavailableError` at the `asyncio.gather` call site -- catching inside each unit coro does not propagate through gather
- In SSE generators: persist rows before LLM call; add explicit `await session.rollback()` in error handler (implicit rollback on session close is insufficient after generator exception)
- Mock: `patch("app.services.<service>.get_settings")` -- settings must be module-level import for this to work

## Imports

- Circular imports: lazy import inside method body -- `from app.runtime.chat_graph import get_chat_graph  # noqa: PLC0415`
- Patch target = where the symbol lives at import time, not where it is called from

## Testing

- `@pytest.mark.slow` for corpus/integration tests that run real ML models
- Book fixture is "The Odyssey" (Butler translation) -- uses "Ulysses" not "Odysseus"
- `conftest_books.py` session fixture ingests all 3 books with real ML, mocks LiteLLM
- Performance tests: `LUMINARY_PERF_TESTS` env guard + `pytest.mark.skipif`
- Retriever main public method: `retrieve(query, document_ids, k)` -- not `search()`

## Summarization

- `SectionSummaryModel`: fields id, document_id, section_id, heading, content, unit_index
- `SummaryModel`: fields id, document_id, mode, content; mode in {executive, detailed, one_sentence}
- Fast path feeds SectionSummaryModel rows to executive LLM; `_is_metadata_section()` filter excludes Gutenberg headers

## Commands

- All uv/pytest commands run from `/Users/sethurama/DEV/LM/learning-mate/backend` (absolute path)
- Run tests: `uv run pytest` (from backend/)
- Run lint: `uv run ruff check .` (from backend/)
- TypeScript: `npx tsc --noEmit` (from frontend/)
