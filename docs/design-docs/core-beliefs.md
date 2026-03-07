# Core Beliefs — Luminary Golden Principles

These principles govern all engineering decisions. They are derived from the OpenAI Harness Engineering framework applied to this project. Every agent working on this codebase must understand and apply them. A recurring background task (ralph) scans for deviations and opens targeted fix-up commits.

---

## 1. CLAUDE.md is the Table of Contents, Not the Encyclopedia

Keep CLAUDE.md (and AGENTS.md) under 100 lines. It is a map, not a manual. All deep context lives in `docs/`. Agents start with the table of contents, follow links to relevant documentation, and are never overwhelmed upfront.

**Rationale**: An agent given a 5,000-line CLAUDE.md wastes context on irrelevant information. A 100-line map pointing to the right doc gets the agent to the relevant detail faster and with less noise.

---

## 2. Repository is the System of Record

All architectural decisions, design choices, patterns, and conventions must live as versioned markdown in `docs/`. If it is not in the repo, the agent cannot see it — and the knowledge is lost when the conversation ends.

**Rationale**: Agents have no persistent memory across sessions. The repository is the only shared, durable memory.

---

## 3. Progressive Disclosure

Agents start with CLAUDE.md as a map, follow links to relevant `docs/`, and are never overwhelmed upfront. Documentation is layered: table of contents → domain overview → deep detail.

**Rationale**: Load context on demand to preserve tokens and clarity. Frontloading all context wastes tokens and confuses agents.

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

**Rationale**: Code that is legible at a glance — explicit names, clear interfaces, documented conventions — reduces agent hallucination and error rates.

---

## 7. Execution Plans are First-Class Artifacts

Active plans live in `docs/exec-plans/active/`, completed plans in `docs/exec-plans/completed/`, known debt in `docs/exec-plans/tech-debt-tracker.md`. All versioned in the repo.

**Rationale**: Agents need to know what work is in progress to avoid conflicts and redundancy. Versioned execution plans create a shared map of current and past work.

---

## 8. Quality Grading in docs/QUALITY_SCORE.md

Grades each product domain and architectural layer, tracks gaps over time. Updated by ralph after each phase.

**Rationale**: Without explicit quality tracking, quality is invisible. A quality score per domain forces honest assessment and guides prioritization of improvement work.

---

## 9. Ephemeral Observability Per Git Worktree

Each ralph iteration boots an isolated app instance with its own logs and metrics. Phoenix traces are worktree-scoped. This means each agent run has its own observable environment without polluting others.

**Rationale**: Multiple concurrent agent runs sharing a single observability namespace create confusion. Isolation enables clean attribution of traces to specific runs.

---

## 10. Technical Debt as Garbage Collection

Pay down debt continuously with automated small PRs, not in painful bursts. The `tech-debt-tracker.md` is the backlog. Ralph addresses debt items in priority order between feature work.

**Rationale**: Deferred debt compounds. Small, regular cleanup is cheaper than emergency refactoring.

---

## 11. Parse and Validate Data at Every Boundary

Never probe data in an ad-hoc way. Always validate inputs with Pydantic (backend) or Zod (frontend). Never pass raw dicts across service boundaries. Every API endpoint accepts a typed Pydantic model.

**Rationale**: Unvalidated data at boundaries is the root cause of most runtime errors and security vulnerabilities. Early validation provides clear error messages and prevents data corruption.

---

## 12. Boring Technology Wins

Well-known, composable, API-stable libraries are easier for agents to reason about. Avoid opaque upstream dependencies where a focused reimplementation would be more legible. Prefer libraries with LLM-friendly documentation.

**Rationale**: Agents reason better about libraries they have seen many times in training data. Novel or obscure libraries require reading source code rather than docs, which wastes context.

---

## 13. Throughput Changes the Merge Philosophy

Minimal blocking merge gates. Short-lived PRs. Corrections are cheap; waiting is expensive. Agent-to-agent review loops replace synchronous human review for routine changes.

**Rationale**: In an agent-assisted workflow, the bottleneck is human review latency. Minimizing blocking gates and shortening PR lifetimes maximizes throughput without sacrificing correctness.

---

## 14. Tests Must Use Real Artifacts at Real Scale

Integration tests must ingest full, untruncated documents. Golden datasets for evaluation must be grounded in actually ingested content with verifiable `context_hint` passages; `document_id: "synthetic"` is never acceptable. Mocking is permitted only at external system boundaries (e.g. LiteLLM to avoid Ollama in CI); core domain services (EmbeddingService, EntityExtractor, chunking, retrieval) must not be mocked in integration tests.

**Rationale**: Tests that mock the thing being tested prove nothing. A passing test suite built on synthetic data and mocked ML services gives false confidence and masks real failures.

---

## 15. Quality Metrics Are CI Gates, Not Reports

Retrieval quality metrics (HR@5, MRR, Faithfulness) must have enforced minimum thresholds that cause `make eval` to exit non-zero when violated. Scores that are merely printed without asserting a threshold are not quality gates — they are noise.

**Rationale**: A metric that cannot fail is not a metric — it is a vanity number. Enforced thresholds are the only mechanism that keeps quality visible and creates accountability for regressions.

---

## 16. Feature Completeness Requires Observable Output in the Running App

A story is not complete when its tests pass. A story is complete when a human can open the running application and observe the feature producing correct output. Demo review gates (stories with `type: "demo-review"`) encode this as a hard checkpoint that cannot be bypassed by an agent.

**Rationale**: Agents write tests that confirm their own implementation. Tests that mock the UI layer can pass while the actual browser experience is broken. Periodic demo review gates create structured moments for human verification.

---

## 17. Offline Degradation Is Explicit, Not Silent

Every feature that depends on an external service (Ollama, OpenAI, Anthropic) must handle the offline case with a user-visible, actionable message. Backend: return HTTP 503 for service unavailability; include the exact start command in the error detail. Frontend: render an inline message naming the service and the command to start it. Silent failures — blank screens, empty lists, generic toasts — are bugs.

**Rationale**: Local-first applications frequently run without all services available. Explicit, actionable error messages are the difference between a tool that works for a developer and one that is abandoned in frustration.

---

## 18. Cache Expensive Intermediate Computations in the Domain Store

Multi-step LLM pipelines that produce an intermediate reduced representation (map-reduce passes, section summaries) must store that intermediate in the same domain store as the final output, using a pseudo-key (e.g. `mode="_map_reduce"` in the summaries table). Do not recompute the same intermediate twice if the inputs haven't changed.

**Rationale**: For large documents, map-reduce requires dozens of sequential LLM calls. Caching the intermediate in the DB means the second summary mode is nearly free, and any future on-demand request also skips the expensive map step entirely.

---

## 19. Pure Functions for Core Domain Logic

Core business logic — retrieval scoring, response parsing, recommendation engines, text transformations — must be pure functions: no I/O, no network calls, no database reads, all inputs as explicit parameters, same output for same inputs. Orchestration layers own the I/O.

```python
# Good — pure, all inputs explicit, testable without mocking
def _split_response(full_text: str) -> tuple[str, list[dict], str]: ...
def _diversify(candidates: list[ScoredChunk], k: int) -> list[ScoredChunk]: ...
def rrf_merge(vector: list[ScoredChunk], keyword: list[ScoredChunk], k: int) -> list[ScoredChunk]: ...
```

**Rationale**: Pure functions are testable with `assert` and no fixture setup. Luminary's `_split_response`, `_diversify`, and `rrf_merge` are all pure; their bugs were caught with unit tests that ran in milliseconds. An equivalent impure function would require a full DB fixture and still not expose the edge cases.

---

## 20. LLM Prompts Must Be Minimal and Unambiguous

System prompts must use plain, direct language with no parentheticals, qualifications, or meta-commentary about the output format. Every word in a system prompt is text the LLM may reproduce verbatim. State each instruction once, directly. The parser must tolerate LLM deviations — one general rule beats two specific regexes.

**Rationale**: The Chat tab showed `ONLY JSON (no prose inside the JSON, do not repeat the answer):` as the visible answer because the system prompt contained that exact phrase and mistral echoed it verbatim. Prevention (simpler prompts) and resilience (general parsing) are both required.

---

## 21. Deterministic Stubs Over MagicMock for Domain Services

When testing code that depends on domain services (EmbeddingService, EntityExtractor, LLM, Retriever), write a minimal stub class that returns fixed, predictable output — not a `MagicMock()` with patched return values.

```python
# Good — a real implementation that returns deterministic output
class _MockEmbeddingService:
    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]
```

Reserve `MagicMock` for external system boundaries only (LiteLLM, httpx, SQLAlchemy internals). Domain service stubs should be plain Python classes with no mock framework dependencies.

**Rationale**: `MagicMock()` confirms that the mock was called, not that the application produced correct output. Deterministic stubs let you assert exact vector dimensions, count rows in LanceDB, and verify retrieval scores. They also prevent the regression where a real service interface changes but the mock silently accepts the old call signature.

---

## 22. Never Implement a Code Path Against Phantom Data

A code path that queries a table only populated by a separate optional story or admin action is a phantom dependency. The path compiles, tests pass (the DB is empty and the code falls through), but the user experience is broken because the required data never exists in a real installation.

Rule: Every primary code path must be tested with real rows in the tables it queries. If a table is populated by a separate story, either: (a) implement the feature against data that IS guaranteed to exist after normal use — e.g. per-document SummaryModel rows written during ingestion, not a LibrarySummaryModel that requires a separate summarize-all call; or (b) mark the story explicitly blocked on the dependency story and do not mark it passes: true.

**Rationale**: Silent fallthrough to a degraded code path is not graceful degradation — it is a feature that appears to work but produces wrong output.

---

## 23. UI Surface Inputs Must Be Mechanical Test Cases for Routing

Any text shown to the user as a suggested action (sample questions, autocomplete, suggested prompts) must be asserted as test inputs for the routing or classification layer that handles them. If the chat UI shows a suggested question, there must be a test asserting it routes to the correct node with the expected intent and confidence.

Rule: When writing or modifying a classifier or router, list every UI-surface example as a parametrized test case. Add new UI examples to the test at the same time they are added to the UI.

**Rationale**: Keyword heuristics fail on natural language variation. Substring matching is brittle. The only mechanical guard is testing the exact strings the user will actually type — the most reliable source of which is the UI's own suggested inputs.

---

## 24. Scope Is a First-Class Routing Dimension, Not Just a Filter

Scope (single document vs. entire library) changes which retrieval strategy is correct, not only which documents are searched. A broad question over the full library requires document-level synthesis (executive summaries per document), not chunk retrieval that is statistically biased toward whichever document has the highest vector similarity. Treating scope purely as a document_id filter is a design error.

Rule: Every strategy node in the chat graph must handle scope=all and scope=single as distinct code paths. For scope=all, broad/exploratory questions route to summary_node (per-document executive summaries), not search_node (chunk retrieval). For comparative queries, each comparison subject is resolved to its own document set, and retrieval runs independently per subject.

**Rationale**: k=10 chunk retrieval across an entire library does not sample documents uniformly — it concentrates on whichever document scores highest for the query. Summary synthesis reads every document equally.
