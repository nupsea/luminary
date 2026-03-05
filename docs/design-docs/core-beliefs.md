# Core Beliefs — Luminary Golden Principles

These principles govern all engineering decisions. They are derived from the OpenAI Harness Engineering framework applied to this project. Every agent working on this codebase must understand and apply them.

---

## 1. CLAUDE.md is the Table of Contents, Not the Encyclopedia

Keep CLAUDE.md (and AGENTS.md) under 100 lines. It is a map, not a manual. All deep context lives in `docs/`. Agents start with the table of contents, follow links to relevant documentation, and are never overwhelmed upfront.

**Rationale**: An agent given a 5,000-line CLAUDE.md wastes context on irrelevant information. A 100-line map pointing to the right doc gets the agent to the relevant detail faster and with less noise.

---

## 2. Repository is the System of Record

All architectural decisions, design choices, patterns, and conventions must live as versioned markdown in `docs/`. If it is not in the repo, the agent cannot see it — and the knowledge is lost when the conversation ends.

**Rationale**: Agents have no persistent memory across sessions. The repository is the only shared, durable memory. Keeping docs in the repo means every future agent can access institutional knowledge.

---

## 3. Progressive Disclosure

Agents start with CLAUDE.md as a map, follow links to relevant `docs/`, and are never overwhelmed upfront. Documentation is layered: table of contents → domain overview → deep detail.

**Rationale**: Frontloading all context wastes tokens and confuses agents. Progressive disclosure means agents load exactly what they need for the current task.

---

## 4. Enforce Invariants Mechanically

Use custom linters with remediation instructions in error messages. CI jobs validate the knowledge base is up to date. Structural tests catch layer violations. Never rely on "the agent will remember the rule."

**Rationale**: Rules that are not mechanically enforced will be violated. Agents (and humans) make mistakes under time pressure. Mechanical enforcement catches violations before they merge.

---

## 5. Layered Domain Architecture

Within each backend domain, dependencies flow forward only: Types → Config → Repo → Service → Runtime → API. Cross-cutting concerns (auth, telemetry, feature flags) enter through explicit Providers. Enforced by linters.

**Rationale**: A strict layer order prevents circular dependencies, makes the codebase predictable for agents to navigate, and keeps each layer independently testable.

---

## 6. Agent Legibility Over Human Style

The codebase is optimised so an agent can reason about the full business domain from the repo itself. Prefer composable, stable, well-documented dependencies. Avoid opaque abstractions that require reading source code to understand.

**Rationale**: Agents write more code than they read. Code that is legible at a glance — explicit names, clear interfaces, documented conventions — reduces agent hallucination and error rates.

---

## 7. Golden Principles in core-beliefs.md

A recurring background task (ralph) scans for deviations from these principles and opens targeted fix-up commits. This file is the canonical source of truth for all engineering values.

**Rationale**: Principles only matter if they are enforced. A recurring scan keeps the codebase aligned with its own stated values without human intervention.

---

## 8. Execution Plans are First-Class Artifacts

Active plans live in `docs/exec-plans/active/`, completed plans in `docs/exec-plans/completed/`, known debt in `docs/exec-plans/tech-debt-tracker.md`. All versioned in the repo.

**Rationale**: Agents need to know what work is in progress to avoid conflicts and redundancy. Versioned execution plans create a shared map of current and past work.

---

## 9. Quality Grading in docs/QUALITY_SCORE.md

Grades each product domain and architectural layer, tracks gaps over time. Updated by ralph after each phase.

**Rationale**: Without explicit quality tracking, quality is invisible. A quality score per domain forces honest assessment and guides prioritization of improvement work.

---

## 10. Ephemeral Observability Per Git Worktree

Each ralph iteration boots an isolated app instance with its own logs and metrics. Phoenix traces are worktree-scoped. This means each agent run has its own observable environment without polluting others.

**Rationale**: Multiple concurrent agent runs sharing a single observability namespace create confusion. Isolation enables clean attribution of traces to specific runs.

---

## 11. Technical Debt as Garbage Collection

Pay down debt continuously with automated small PRs, not in painful bursts. The `tech-debt-tracker.md` is the backlog. Ralph addresses debt items in priority order between feature work.

**Rationale**: Deferred debt compounds. Small, regular cleanup is cheaper than emergency refactoring. Automation makes debt paydown frictionless.

---

## 12. Parse and Validate Data at Every Boundary

Never probe data in an ad-hoc way. Always validate inputs with Pydantic (backend) or Zod (frontend). Never pass raw dicts across service boundaries. Every API endpoint accepts a typed Pydantic model.

**Rationale**: Unvalidated data at boundaries is the root cause of most runtime errors and security vulnerabilities. Early validation provides clear error messages and prevents data corruption.

---

## 13. Boring Technology Wins

Well-known, composable, API-stable libraries are easier for agents to reason about. Avoid opaque upstream dependencies where a focused reimplementation would be more legible. Prefer libraries with LLM-friendly documentation.

**Rationale**: Agents reason better about libraries they have seen many times in training data. Novel or obscure libraries require reading source code rather than docs, which wastes context.

---

## 14. Throughput Changes the Merge Philosophy

Minimal blocking merge gates. Short-lived PRs. Corrections are cheap; waiting is expensive. Agent-to-agent review loops replace synchronous human review for routine changes.

**Rationale**: In an agent-assisted workflow, the bottleneck is human review latency. Minimizing blocking gates and shortening PR lifetimes maximizes throughput without sacrificing correctness — corrections can always be made in follow-up commits.

---

## 15. Tests Must Use Real Artifacts at Real Scale

Integration tests must ingest full, untruncated documents — not truncated fixtures. Golden datasets for evaluation must be grounded in actually ingested content with verifiable `context_hint` passages; synthetic or fictional data with `document_id: "synthetic"` is never acceptable. Mocking is permitted only at external system boundaries (e.g. LiteLLM to avoid Ollama in CI); core domain services (EmbeddingService, EntityExtractor, chunking, retrieval) must not be mocked in integration tests. Slow tests (`@pytest.mark.slow`) run against real ML services; fast tests (`make test`) mock only at the boundary.

**Rationale**: Tests that mock the thing being tested prove nothing. A passing test suite built on synthetic data and mocked ML services gives false confidence and masks real failures. The cost of slow tests is latency; the cost of fake tests is undetected regressions in production.

---

## 16. Quality Metrics Are CI Gates, Not Reports

Retrieval quality metrics (HR@5, MRR, Faithfulness) must have enforced minimum thresholds that cause `make eval` to exit non-zero when violated. Scores that are merely printed without asserting a threshold are not quality gates — they are noise. Thresholds must be defined in code, score history must be committed to the repo, and any PR that regresses a metric below its threshold must be explicitly justified before merge.

**Rationale**: A metric that cannot fail is not a metric — it is a vanity number. Enforced thresholds are the only mechanism that keeps quality visible and creates accountability for regressions. Without them, retrieval quality silently degrades across iterations.

---

## 17. Feature Completeness Requires Observable Output in the Running App

A story is not complete when its tests pass. A story is complete when a human can open the running application and observe the feature producing correct output. Backend endpoints existing does not mean the feature is working — the UI must render the data, the pipeline must be wired end-to-end, and every state (loading, error, empty, populated) must be visible. Demo review gates (stories with `type: "demo-review"`) encode this as a hard checkpoint that cannot be bypassed by an agent.

**Rationale**: Agents write tests that confirm their own implementation. Tests that mock the UI layer can pass while the actual browser experience is broken. The only reliable check is a human running the full application against real data. Periodic demo review gates create structured moments for this verification before the codebase moves forward.

---

## 18. Offline Degradation Is Explicit, Not Silent

Every feature that depends on an external service (Ollama, OpenAI, Anthropic) must handle the offline case with a user-visible, actionable message. Backend: return HTTP 503 (not 500) for service unavailability; include the exact start command in the error detail. Frontend: check the HTTP status code and render an inline message naming the service and the command to start it. Silent failures — blank screens, empty lists, spinning indicators that never resolve, generic "something went wrong" toasts — are bugs, not graceful degradation. The user must always know what is wrong and what to do about it.

**Rationale**: Local-first applications frequently run without all services available. Ollama in particular is commonly offline during development. An application that silently fails when Ollama is down is unusable and undebugable. Explicit, actionable error messages are the difference between a tool that works for a developer and one that is abandoned in frustration.

---

## 19. asyncio Background Tasks Must Hold Strong References

Python's event loop holds only **weak references** to tasks created with `asyncio.create_task()`. A task without an external strong reference can be garbage-collected mid-execution — producing partial results that are silent and hard to diagnose (e.g., the first loop iteration stores data but subsequent iterations are never run). Always store task references in a module-level set and register a done-callback to clean up:

```python
_background_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(some_coroutine())
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

**Rationale**: Background tasks for expensive post-processing (e.g. pre-generating summaries after ingestion) are the canonical use case. A task that gets GC'd after storing only the first result and silently dropping the rest creates a class of partial-write bugs that have no stack trace and no error log — they are invisible until you query the database and notice missing rows.

---

## 20. Cache Expensive Intermediate Computations in the Domain Store

Multi-step LLM pipelines that produce an intermediate reduced representation (map-reduce passes, section summaries, retrieval-augmented contexts) must store that intermediate in the same domain store as the final output, using a pseudo-key (e.g. `mode="_map_reduce"` in the summaries table). This converts N×(map_cost + final_cost) into 1×map_cost + N×final_cost across all consumers — whether those are multiple modes in a single run or separate on-demand requests from the UI.

Do not recompute the same intermediate twice if the inputs haven't changed. The domain store is the cache.

**Rationale**: For large documents, map-reduce requires dozens of sequential LLM calls. Running this step once per summary mode (4 modes = 4× the LLM budget) wastes resources and user time. Caching the intermediate in the DB means the second mode is nearly free, and any future on-demand request for a new mode also skips the expensive map step entirely.

---

## 21. Batch ML Inference Calls — Never Loop Per-Item

CPU-bound ML models (GLiNER NER, embedding models) expose batch APIs that execute a single forward pass over multiple inputs. Always use the batch API:

- NER: `model.batch_predict_entities(texts, labels)` not `for t in texts: model.predict_entities(t, labels)`
- Embeddings: `embedder.encode(texts)` not `for t in texts: embedder.encode([t])`

A per-item loop scales linearly with document size. A batch call of N items typically takes 2–4× the time of a single call — not N×. The speedup on CPU is 4–8×. Every per-item loop on a CPU-bound model is a performance bug.

**Rationale**: NER on a 600-chunk document ran in ~12 minutes per-item vs ~3 minutes with batching. This is not a micro-optimisation — it is the difference between a usable ingestion pipeline and one that makes the laptop fan audible for every uploaded book.

---

## 22. Pure Functions for Core Domain Logic

Core business logic — retrieval scoring, response parsing, recommendation engines, text transformations — must be pure functions: no I/O, no network calls, no database reads, all inputs as explicit parameters, same output for same inputs. Orchestration layers (`QAService`, `stream_answer`, workflow nodes) call these pure functions and own the I/O.

```python
# Good — pure, all inputs explicit, testable without mocking
def _split_response(full_text: str) -> tuple[str, list[dict], str]: ...
def _diversify(candidates: list[ScoredChunk], k: int) -> list[ScoredChunk]: ...
def rrf_merge(vector: list[ScoredChunk], keyword: list[ScoredChunk], k: int) -> list[ScoredChunk]: ...

# Bad — business logic entangled with DB read
async def rrf_merge(vector, keyword, k, session):
    doc = await session.get(DocumentModel, ...)  # impure, untestable without DB
```

**Rationale**: Pure functions are testable with `assert` and no fixture setup. Luminary's `_split_response`, `_diversify`, and `rrf_merge` are all pure; their bugs were caught and fixed with a handful of unit tests that ran in milliseconds. An equivalent impure function would require a full DB fixture, a mock retriever, and an async test runner — and would still not expose the edge cases that `pytest.approx` or direct string assertions expose immediately.

---

## 23. LLM Prompts Must Be Minimal and Unambiguous

System prompts must use plain, direct language with no parentheticals, qualifications, or meta-commentary about the output format. Every word in a system prompt is text the LLM may reproduce verbatim in its response. Instructions that explain themselves (`"output ONLY this JSON (no prose inside the JSON, do not repeat the answer):"`) are echoed by smaller models as literal output, corrupting the response.

Rules:
- State the instruction once, directly: `"Write your answer as prose. Then on a new line write this JSON:"`
- Never include parenthetical qualifiers inside the instruction: no `(don't do X)`, no `ONLY`, no multi-clause constraints
- The parser must tolerate LLM deviations (echoed labels, style variants) — one general rule beats two specific regexes

**Rationale**: The Chat tab showed `ONLY JSON (no prose inside the JSON, do not repeat the answer):` as the visible answer because the system prompt contained that exact phrase and mistral echoed it verbatim. The fix required both simplifying the prompt (prevention) and replacing two hardcoded stripping regexes with one general rule that strips any trailing line mentioning "json" (resilience). Prevention and resilience are both required — neither alone is sufficient.

---

## 24. Structured Logging Only — No print() in Library Code

All log output in `app/` must use `logger = logging.getLogger(__name__)`. Never use `print()` outside of CLI entry points and debug scripts. Log levels must be used correctly: `DEBUG` for operational traces, `INFO` for lifecycle events, `WARNING` for recoverable failures, `ERROR` for unhandled exceptions.

```python
# Good
logger = logging.getLogger(__name__)
logger.debug("vector_search: LanceDB table empty, returning []")
logger.warning("stream_answer: LLM call failed", extra={"model": model}, exc_info=exc)

# Bad — stdout pollution, not configurable, leaks into SSE streams
print(f"DEBUG: chunks={len(chunks)}")
```

**Rationale**: `print()` statements in library code pollute stdout, leak into SSE event streams, cannot be silenced without monkeypatching, and provide no level filtering. Structured logging with `getLogger(__name__)` is configurable per-module, captured by test log collectors, and shows the calling module automatically. In an async streaming application a stray `print()` can corrupt a Server-Sent Events response.

---

## 25. Deterministic Stubs Over MagicMock for Domain Services

When testing code that depends on domain services (EmbeddingService, EntityExtractor, LLM, Retriever), write a minimal stub class that returns fixed, predictable output — not a `MagicMock()` with patched return values. Stubs are real implementations of the interface contract; mocks are illusions that test the mock itself.

```python
# Good — a real implementation that returns deterministic output
class _MockEmbeddingService:
    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]  # fixed vector, exact assertions possible

# Bad — tests that the mock was called, not that the system behaved correctly
mock_embedder = MagicMock()
mock_embedder.encode.return_value = MagicMock()  # vague, assertions are checks on call counts
```

Reserve `MagicMock` for external system boundaries only (LiteLLM, httpx, SQLAlchemy internals) where you cannot write a real stub. Domain service stubs should be plain Python classes with no mock framework dependencies.

**Rationale**: `MagicMock()` creates objects that accept any attribute access and return other `MagicMock` objects. Tests built on them confirm that the mock was called, not that the application produced correct output. A `_MockEmbeddingService` that returns `[[0.1] * 1024]` lets you assert exact vector dimensions, count rows in LanceDB, and verify retrieval scores — none of which are possible with a vague mock. Deterministic stubs also prevent the class of regression where a real service interface changes but the mock silently continues accepting the old call signature.
