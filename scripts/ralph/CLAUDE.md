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

1. Read `scripts/ralph/prd.json` — tech stack, stories, data model
2. Read `scripts/ralph/progress.txt` — check `## Codebase Patterns` section first (create file if missing)
3. Check you are on branch matching `prd.branchName`. Create from main if missing.
4. Pick the **lowest priority number** story where `passes: false`
4a. If the story has `"type": "demo-review"`, check for `scripts/ralph/demo-reviews/[story-id]-approved.md` containing `APPROVED` on line 1. If absent: output `BLOCKED: Demo Review Gate [id] requires human approval` and stop. Do NOT implement code for demo-review stories — only create the demo-reviews/ directory and README.md, then stop.
5. Implement that single story — stay focused, minimal changes
6. Run quality checks. If `Makefile` exists: `make ci`. Otherwise run individually: `cd backend && uv run ruff check . && uv run pytest`, `cd frontend && npx tsc --noEmit && npm run build`
7. If a check fails: read the error message — it contains remediation instructions. Fix, do not bypass.
8. Commit with message: `feat: [Story ID] - [Story Title]`
9. Set `passes: true` for the completed story in `scripts/ralph/prd.json`
10. Append progress to `scripts/ralph/progress.txt`
11. If `scripts/ralph/doc_gardener.py` exists: run `python scripts/ralph/doc_gardener.py` and fix any stale doc warnings. Skip this step if the file does not exist yet.

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
11. Integration tests use real, untruncated documents. Never truncate fixtures. Never mock core domain services (embedder, NER, retrieval) in integration tests — only mock at external system boundaries (LiteLLM, HTTP). See core-beliefs.md §15.
12. Golden evaluation datasets must be grounded in actually ingested content with verifiable context passages. `document_id: "synthetic"` is never acceptable. Quality metrics must assert thresholds, not just print scores. See core-beliefs.md §16.
13. Every frontend story must implement three states: loading (skeleton, not spinner blocking the page), error (inline message per section — not blank), and empty (explicit empty state, not blank). `Promise.all` is banned for independent data fetches — use `Promise.allSettled` so one failure does not block the rest. Every acceptance criterion for a frontend feature must include one criterion each for the loading state, error state, and empty state.
14. Upload and long-running operations must show inline progress (inside the triggering UI element, not only in a toast). The triggering dialog/panel stays open until the operation completes or fails. Errors surface inline with a retry option.
15. Demo review gates are human-only checkpoints. For any story where `"type": "demo-review"` is set in prd.json, ralph must check for the file `scripts/ralph/demo-reviews/[story-id]-approved.md` containing `APPROVED` on line 1 before setting `passes: true`. Ralph must NEVER create this file. If absent, ralph outputs: `BLOCKED: Demo Review Gate [id] requires human approval` and stops.
16. Every user-facing feature story must ship a smoke test: an executable shell script at `scripts/smoke/[story-id].sh` that calls `localhost:8000` over real HTTP using curl and asserts a non-error response (HTTP 2xx, non-empty body). Smoke tests must not mock anything. `make smoke` runs all smoke scripts sequentially.
17. End-to-end integration tests must span the COMPLETE pipeline: ingest → retrieve → QA answer → graph. A test that only covers one pipeline node (embedding only, search only) does NOT satisfy this requirement. The test file `test_e2e_book.py` is the canonical full-pipeline test.
18. Offline degradation is explicit and actionable. When Ollama is unreachable, every LLM-dependent feature must display an inline error message that names the unavailable service and the exact command to start it (`ollama serve`). Blank screens, generic 500 errors, and silent empty results are bugs. HTTP 503 (not 500) must be returned from the backend. The frontend must check the status code and display the correct message.

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
Blocked on a demo-review gate → reply: `BLOCKED: Demo Review Gate [id] requires human approval. See scripts/ralph/demo-reviews/README.md.` and stop.
Otherwise end normally; the next iteration continues.
