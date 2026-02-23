# Ralph — Luminary Agent Instructions

You are an autonomous coding agent. Humans steer; agents execute.
Read this file as a MAP. Follow the links below for deeper context.

## Deep Context (read before starting any story)

- Architecture & domains → `docs/ARCHITECTURE.md`
- Golden principles / core beliefs → `docs/design-docs/core-beliefs.md`
- Quality grades per domain → `docs/QUALITY_SCORE.md`
- Known tech debt → `docs/exec-plans/tech-debt-tracker.md`
- Frontend conventions → `docs/FRONTEND.md`
- Active execution plans → `docs/exec-plans/active/`
- Tool references (uv, LanceDB, LangGraph, Kuzu, FSRS) → `docs/references/`

## Your Task Loop

1. Read `prd.json` (same directory as this file) — tech stack, stories, data model
2. Read `progress.txt` — check `## Codebase Patterns` section first
3. Check you are on branch `prd.branchName`. Create from main if missing.
4. Pick the **lowest priority number** story where `passes: false`
5. Implement that single story — stay focused, minimal changes
6. Run quality checks: `make ci` (or individually: `uv run ruff check .`, `uv run pytest`, `npx tsc --noEmit`)
7. If a check fails: read the error message — it contains remediation instructions. Fix, do not bypass.
8. Commit with message: `feat: [Story ID] - [Story Title]`
9. Set `passes: true` for the completed story in `prd.json`
10. Append progress to `progress.txt`
11. Run `python scripts/ralph/doc_gardener.py` — fix any stale doc warnings before stopping

## Ten Invariants (enforced mechanically — never violate)

1. Python: `uv` only. Never pip, Poetry, or pipenv. `uv run` for all commands.
2. Python runtime: 3.13. Specify in pyproject.toml `requires-python = ">=3.13"`.
3. Layer order: Types → Config → Repo → Service → Runtime → API. No reverse imports.
4. Validate at every boundary. All FastAPI inputs are Pydantic models. No raw dicts.
5. All LLM calls go through LiteLLM. Never call OpenAI/Anthropic/Ollama SDKs directly.
6. Structured logging only. No `print()` in app/ code. Use `logger = logging.getLogger(__name__)`.
7. No manually-written code outside prd.json stories. Every change must map to a story.
8. Docs are the system of record. If you learn something reusable, encode it in `docs/`.
9. Tests required. Every new service or endpoint must have at least one pytest test.
10. TypeScript strict mode. `tsc --noEmit` must pass. No `any` without a comment justifying it.

## Progress Report Format

APPEND to progress.txt (never replace):
```
## [ISO timestamp] - [Story ID] - [Story Title]
- Implemented: [what was built]
- Files changed: [list]
- Learnings:
  - [pattern/gotcha discovered]
---
```

## Codebase Patterns (read first, update when you find new patterns)

Maintained in `## Codebase Patterns` section at TOP of progress.txt.

## Stop Condition

All stories `passes: true` → reply: <promise>COMPLETE</promise>
Otherwise end normally; the next iteration continues.
