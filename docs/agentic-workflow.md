# Agentic Workflow — Luminary

Patterns for efficient agent-assisted development using Ralph and Claude Code. Based on ECC (Everything Claude Code) principles applied to the Luminary stack.

---

## Model Routing

Route sub-tasks to the cheapest capable model. Token cost is the primary lever on agent throughput — a 60-iteration Ralph run costs 4× less when exploration uses Haiku.

| Task | Model | Reason |
|------|-------|--------|
| File search, doc reads, pattern lookup | Haiku | Fast, cheap — correct on simple lookups |
| Multi-file implementation, code review | Sonnet | Best balance for coding tasks |
| Cross-domain refactor, architecture decision | Sonnet via luminary-planner agent | Planning focus with read-only tools |
| Post-story quality review | Sonnet via luminary-reviewer agent | Structured review checklist |
| QUALITY_SCORE.md, tech-debt-tracker updates | Haiku via luminary-docs agent | Structured doc writes, no reasoning needed |

Operative rule: **exploration is cheap; implementation is medium; architecture is deliberate.** Match model cost to task complexity.

---

## Available Agents

Agents live in `.claude/agents/`. They are invoked via the Task tool or automatically by Claude Code when the description matches the task.

### luminary-planner (Sonnet)

Use before implementing a new story or architectural change.

- Reads: `docs/ARCHITECTURE.md`, `core-beliefs.md`, `QUALITY_SCORE.md`, `tech-debt-tracker.md`, `prd.json`
- Produces: file-level impact list, ordered implementation steps, acceptance criteria, risk flags
- Tools: Read, Grep, Glob, Bash (read-only — cannot modify files)

**When to invoke**: Before writing any code for a story that touches 3+ files, crosses domain boundaries, or involves a new service.

### luminary-reviewer (Sonnet)

Use after implementing a story or significant change.

- Runs: `ruff check`, `pytest -x`, `tsc --noEmit`
- Checks: layer order, LiteLLM gateway, `print()` violations, test coverage, frontend three-state completeness
- Produces: prioritised issue list (Critical / High / Low) with file:line citations
- Tools: Read, Grep, Glob, Bash

**When to invoke**: Before committing, after any backend service change, or when a quality check produces an unexpected failure.

### luminary-docs (Haiku)

Use after a story completes or a new pattern is discovered.

- Updates: `QUALITY_SCORE.md`, `tech-debt-tracker.md`, `ARCHITECTURE.md`, `docs/references/`
- Tools: Read, Edit, Write, Grep (no Bash — no test execution)

**When to invoke**: After a phase completes (update quality grades), after a reviewer flags a low-priority issue (add tech debt entry), after a new pattern is discovered during implementation.

---

## Hook-Based Enforcement

Project hooks run automatically via `.claude/settings.json`. They enforce invariants at the tool boundary — before or after each tool call — without requiring the agent to remember the rule.

| Hook | Trigger | Action |
|------|---------|--------|
| `pre-pip-blocker` | Bash with `pip install` | **Blocks** (exit 2) + remediation message |
| `pre-direct-llm-blocker` | Bash installing `openai`/`anthropic` directly | **Blocks** (exit 2) + remediation message |
| `post-python-lint` | Edit/Write on `*.py` in `backend/` | Runs `ruff check` async, writes warnings to stderr |

Hooks complement CI — they are the fast-feedback layer, not the authoritative gate. CI (`make ci`) remains the final arbiter.

---

## Ralph Context Optimization

`prd.json` is 209KB. Reading the full file on every Ralph iteration wastes context. Extract only pending stories:

```python
import json
with open("scripts/ralph/prd.json") as f:
    prd = json.load(f)
pending = [s for s in prd["stories"] if not s.get("passes")]
pending.sort(key=lambda s: s["priority"])
next_story = pending[0]  # work on this
```

For completed stories, you only need their IDs (to verify branch alignment) — not their full description or acceptance criteria.

---

## Multi-Session Memory

Ralph accumulates learnings in `scripts/ralph/progress.txt` under the `## Codebase Patterns` section at the top. This is the persistent memory across Ralph iterations. Always read it before starting a story.

For interactive sessions, use `.claude/` memory files (auto-maintained by Claude Code). Key patterns discovered interactively should also be encoded in `docs/` (belief #2: repo is system of record) so Ralph can access them.

---

## Parallelization

For independent stories that touch different domains, run parallel Ralph instances using git worktrees:

```bash
git worktree add ../luminary-feature-b feature-b
# Run ./scripts/ralph/ralph.sh in each worktree independently
```

Parallel execution is safe when stories do not share modified files. Check `prd.json` story descriptions for file overlap before parallelizing.

---

## Quality Gates Summary

| Gate | Command | Enforced By |
|------|---------|-------------|
| Python lint | `cd backend && uv run ruff check .` | Hook (async) + `make ci` |
| Python tests | `cd backend && uv run pytest` | `make ci` |
| TypeScript types | `cd frontend && npx tsc --noEmit` | `make ci` |
| Frontend build | `cd frontend && npm run build` | `make ci` |
| Smoke tests | `make smoke` | Manual / Ralph step 11 |
| Retrieval eval | `make eval` | Manual — asserts HR@5/MRR thresholds |
| Demo review gate | `scripts/ralph/demo-reviews/[id]-approved.md` | Ralph step 4a |
