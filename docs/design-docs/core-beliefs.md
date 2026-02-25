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
