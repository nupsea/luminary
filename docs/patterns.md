# Luminary Backend Patterns

Patterns discovered through completed stories. Read before implementing new features.

## DateTime and Timezones

- **SQLite aiosqlite tz-naive columns**: aiosqlite returns DateTime columns as tz-naive even when stored from tz-aware datetimes. Any service comparing stored timestamps against `datetime.now(UTC)` must normalize first: `dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt`.

## Business Logic Patterns

- **Streak computation**: collect distinct UTC dates from completed rows into a `set[date]`, then walk back day-by-day from today checking set membership. Avoids window functions and works reliably across SQLite.
- **Single-active-resource invariant**: enforce in service via a query filter (e.g., `_get_active_or_paused()`) + a typed exception (e.g., `ActiveSessionExists(existing_id)`); map the exception to HTTP 409 in the router with `existing_id` in the detail payload.
- **Service-level ON DELETE SET NULL**: SQLite cannot ALTER ADD FK, so implement cascade-delete logic in the service. Before deleting a parent row whose ID is referenced by a nullable column in a child table, run `UPDATE child_table SET fk_col=NULL WHERE fk_col=:parent_id`; the FK column remains a plain nullable index. This pattern applies to any ownership relationship where foreign keys cannot be declared.
- **Type-dispatched compute methods**: keep the dispatcher trivial -- a series of `if self.type == 'A': return await self._compute_A()` branches ending with `raise InvalidType`. Each branch is independently testable and logic stays out of the dispatcher.
- **Subprocess backend URL constant**: When launching subprocesses from within a backend service (e.g., eval runner), they need to reach the backend API. Store the URL as a module-level constant (`_BACKEND_URL = "http://localhost:7820"`) and pass it as `--backend-url` to all subprocess invocations. Avoids hard-coded ports scattered across code.

## Database Migrations and Schema Evolution

- **Replace model in-place with table name unchanged**: keep the SQLAlchemy class declaration as the new schema (so `create_all` generates the correct CREATE TABLE for fresh databases) and add idempotent ALTER TABLE statements in `db_init.py` for existing databases with the old schema. New columns are nullable by default; legacy NOT NULL columns in old databases are tolerated by the new model if it declares them nullable.
- **Long-running uvicorn --reload and schema mutations**: the file-watcher does not invalidate the SQLAlchemy connection pool's cached prepared-statement metadata when a table is dropped or recreated outside the process. After a manual DROP/CREATE on a watched table, restart the worker (kill and relaunch); --reload alone is insufficient.

## Search and Retrieval

- **Asymmetric query expansion for hybrid search**: SQLite FTS5 MATCH uses implicit AND across tokens, so appending tokens absent from the corpus collapses BM25 recall to zero. Route different expansions to different tiers: feed expansion (e.g., graph-augmented entity tokens) to dense vector search (which rewards semantic similarity regardless of exact token match), and keep keyword (FTS5) search on the original query. Exception: HyDE-style hypothetical-answer expansion is generated to look like source text and can flow into both because it shares vocabulary with the corpus.

## FastAPI Routing

- **Literal vs. parametric endpoint ordering**: register literal-segment endpoints (e.g., `/resource/active`, `/resource/stats`) BEFORE `/resource/{id}/...` so the router does not match the literal segment as a path parameter.
- **HTTP 204 responses**: use `Response(status_code=204)` directly; FastAPI cannot serialize a `None` body via `response_model=` decorator.
- **Polymorphic JSONL field normalization at API boundary**: Golden JSONL files may have `context_hint` as string or list of strings. Normalize at the API response builder, not in consumers: `def _str_hint(raw: object) -> str | None: return None if raw is None else (" ".join(str(s) for s in raw) if isinstance(raw, list) else str(raw))`. This pattern applies to any JSONL ingestion where fields have variable types.

## Testing

- **In-memory SQLite with isolation**: `make_engine("sqlite+aiosqlite:///:memory:")` + `create_all_tables()` + monkeypatch `db_module._engine` and `db_module._session_factory`. Effective for new domains where integration tests use a fresh in-memory database per test.
- **Stale .pyc bytecode masking test failures**: When a test fails on a code path it does not logically exercise, suspect cached bytecode before the source. Run `find . -name __pycache__ -type d -exec rm -rf {} +` to clear all .pyc files. The cached bytecode can be stale after code changes and cause mismatches between what you wrote and what Python executes.
- **Patch target for lazy-imported helpers**: When a helper imports a symbol inside its function body (e.g., `from app.services.X import fn  # noqa: PLC0415`), the patch target is `app.services.X.fn` (where the symbol is defined), NOT `app.services.retriever.fn` (the call site). The lazy import re-resolves the symbol at runtime, so mocking the call-site import does not intercept the lazy fetch.

## Frontend

- **Button-based tab nav with hash persistence**: @radix-ui/react-tabs may not be installed; use state-driven buttons + `window.location.hash` for URL persistence. Initialize tab from hash: `const [activeTab, setActiveTab] = useState(() => { const hash = window.location.hash.replace('#', '') as TabId; return TABS.some(t => t.id === hash) ? hash : 'default' })`. On change: `setActiveTab(tab); window.location.hash = tab`. Style with `border-b-2 border-primary` for active, `border-transparent` for inactive.
- **localStorage snapshot for persistent UI state**: module-level `readSnapshot()`, `writeSnapshot()`, `clearSnapshot()` triplet in Zustand modules; read snapshot at module load to seed initial state; call `writeSnapshot()` in a `useEffect` on every state change. On component mount, reconcile with server (e.g., `GET /resource/active`); if server has no record, `clearSnapshot()` and reset to idle; otherwise hydrate from server response. Critical: module-level read happens once per page load, so every state mutation must call `writeSnapshot()` to persist across refresh.
- **Vitest for pure logic only**: vitest config uses "node" environment (not jsdom). Convention: extract pure functions into helpers (lib/ or store/) and unit-test those; do NOT mount React components in vitest tests. See ClozeCard.test.ts and focusUtils.test.ts as canonical patterns.
- **409 conflict-with-id discriminated union**: when an endpoint returns 409 with a conflicting resource ID, type the response as `Resource | { status: 409; existing_id_field: string }`. Fetch wrapper returns the right branch based on `res.status` -- callers stay type-safe without try/catch.
- **Web Audio API chime**: use `new (window.AudioContext || window.webkitAudioContext)()` + oscillator + gain envelope for local-first chime without bundling binary audio files. Close context via `osc.onended` to avoid leaking contexts on repeated firing. Respect a mute toggle in store.
- **Phase-aware setInterval cleanup**: gate `setInterval` with a `useEffect` that depends on `phase`. Cleanup runs whenever phase changes, so paused phase naturally halts the interval; resume phase restarts it without manual clearing.
- **Tick-driven timer auto-completion**: keep store side-effect-free. Pin auto-complete logic in a separate `useEffect` on `secondsLeft === 0` (gated by phase + sessionId + a ref latch to avoid double-fire) -- component owns API calls, store owns state.
- **useQueries for N independent list-item fetches**: use `useQueries()` instead of mapping `useQuery()` calls (which violates rules of hooks). Each item query fails independently; react-query dedupes identical queryKey patterns. Useful pattern for per-item progress/metadata fetches on a list.
- **shadcn Sheet for side-panel surfaces**: use the existing Sheet primitive for detail panels or side drawers; supports `side="right"`, `side="left"`, `side="top"`, `side="bottom"`. No extra dependencies required -- prefer Sheet over building one-off drawer components.
- **Delete dead consumer code when backend API changes**: when a backend story replaces a public API contract (e.g., removing an endpoint or changing the response shape), the matching frontend story must delete the dead consumer code in the same commit. Greppable check: after the backend merges, search the frontend for any reference to the removed endpoint or old field name (e.g., `document_id-on-goal`, `/readiness`).
- **Inline computed-icon JSX wrapper**: when rendering a component from a mapped object (e.g., `GOAL_TYPE_ICON[key]`), JSX requires a capitalized identifier in scope. Use an IIFE: `{(() => { const Icon = MAP[k]; return <Icon /> })()}` instead of the invalid `<MAP[k] />`.
- **Cross-tab cache invalidation on session completion**: when a background event (e.g., auto-complete on pomodoro) completes a session linked to a goal, invalidate the goal's progress query (`["goal-progress", goalId]`), linked sessions query (`["goal-sessions", goalId]`), and the goals list query (`["goals"]`) to keep all surfaces in sync without refetch staleness windows.
