# Luminary Invariants

These invariants are mechanically enforced. Violating any of them will cause CI to fail. Read the error messages — they contain remediation instructions.

## 1. uv only — never pip or Poetry

```bash
# Correct
cd backend && uv add <package>
cd backend && uv run ruff check .

# Wrong — will be blocked by PreToolUse hook
pip install <package>
poetry add <package>
```

## 2. Python 3.13

`pyproject.toml` must declare `requires-python = ">=3.13"`. Never use 3.11 or 3.12 syntax features that don't backport.

## 3. Layer order: Types → Config → Repo → Service → Runtime → API

Within each backend domain, imports must flow forward only. A Service file may import from Repo and Types. A Repo file may import from Types and Config. An API file may import from Service. Reverse imports are architecture violations.

## 4. All FastAPI inputs are Pydantic models — no raw dicts

```python
# Correct
class SearchRequest(BaseModel):
    query: str
    k: int = 10

@router.post("/search")
async def search(req: SearchRequest): ...

# Wrong
@router.post("/search")
async def search(body: dict): ...
```

## 5. All LLM calls go through LiteLLM — never call provider SDKs directly

```python
# Correct
import litellm
response = await litellm.acompletion(model="ollama/mistral", messages=...)

# Wrong — blocked by PreToolUse hook
import openai
client = openai.OpenAI()
```

## 6. Structured logging only — no print() in app/

```python
# Correct
logger = logging.getLogger(__name__)
logger.debug("chunk count: %d", len(chunks))

# Wrong
print(f"DEBUG: chunks={len(chunks)}")
```

## 7. Every change maps to a story in prd.json

No manually-written code outside of story scope. If a pattern change is needed that no story covers, create a story first.

## 8. Docs are the system of record

If you learn a reusable pattern, encode it in `docs/`. Comments in code are acceptable for implementation details; architectural decisions belong in `docs/design-docs/`.

## 9. Tests required

Every new service method or API endpoint must have at least one pytest test. Every new frontend page or significant component must have a smoke test at `scripts/smoke/[story-id].sh`.

## 10. TypeScript strict mode

`tsc --noEmit` must pass. Never use `any` without a comment explaining why. Never suppress type errors with `@ts-ignore` without explanation.

## 11–18 (Extended)

See `scripts/ralph/CLAUDE.md` for invariants 11–18 covering integration tests, golden datasets, frontend states, upload progress, demo gates, smoke tests, e2e tests, and offline degradation.
