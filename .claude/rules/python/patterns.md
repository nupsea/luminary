# Luminary Python Patterns

Recurring patterns confirmed across multiple stories. Read before writing any Python code.

## Package Management

```bash
# Install a new package
cd backend && uv add <package>

# Run any command in the venv
cd backend && uv run <command>

# Run tests
cd backend && uv run pytest

# Run linter
cd backend && uv run ruff check .
cd backend && uv run ruff check --fix .
```

## Settings Singleton

```python
# config.py — always use @lru_cache, never instantiate Settings directly
from functools import lru_cache

class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ...

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

## FastAPI Lifespan (not deprecated on_event)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await db_init()
    yield
    # shutdown
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

## Background Tasks with Strong References

```python
# asyncio holds only weak refs — tasks without a strong ref get GC'd mid-execution
_background_tasks: set[asyncio.Task] = set()

def fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
```

## LiteLLM for All LLM Calls

```python
import litellm

# Async completion
response = await litellm.acompletion(
    model="ollama/mistral",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.0,
)
text = response.choices[0].message.content

# Streaming
async for chunk in await litellm.acompletion(..., stream=True):
    delta = chunk.choices[0].delta.content or ""
```

## Structured Logging

```python
import logging
logger = logging.getLogger(__name__)

# Use % formatting — not f-strings (avoids formatting cost on filtered levels)
logger.debug("retrieved %d chunks for query=%r", len(chunks), query[:50])
logger.warning("Ollama unreachable: %s", exc, exc_info=exc)
```

## Offline Degradation — HTTP 503

```python
from fastapi import HTTPException

try:
    result = await litellm.acompletion(...)
except litellm.ServiceUnavailableError as exc:
    raise HTTPException(
        status_code=503,
        detail="Ollama is unreachable. Start it with: ollama serve",
    ) from exc
```

## Batch ML Inference — Never Per-Item Loop

```python
# Correct — single forward pass
embeddings = embedder.encode(texts)          # list[list[float]]
entities = model.batch_predict_entities(texts, labels)

# Wrong — N forward passes
embeddings = [embedder.encode([t])[0] for t in texts]
```

## uv Commands Must Run From /backend

```bash
# All uv/ruff/pytest commands require the backend directory as CWD
cd backend && uv run pytest tests/
# NOT: uv run pytest backend/tests/  (will fail to find pyproject.toml)
```

## Pytest Exit Code 5 = No Tests Collected (Acceptable at Scaffold)

If `pytest` exits with code 5, it means no test files matched — not a failure. This is acceptable when scaffolding a new domain before tests are written.

## AsyncIO Test Setup

```python
import pytest

@pytest.mark.asyncio
async def test_something():
    result = await some_async_function()
    assert result is not None
```
