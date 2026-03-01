# Luminary

Luminary is a local-first personal knowledge and learning assistant. It ingests your documents (PDFs, books, papers, conversations, notes, and code), builds a queryable knowledge graph, and turns content into spaced-repetition flashcards — all running on your machine with no data leaving your device unless you configure a cloud LLM key.

## Architecture Overview

```
Types → Config → Repo → Service → Runtime → API
  ↑                                           ↑
  └─────── 6-layer dependency rule ───────────┘

Navigation tabs:  Learning | Chat | Viz | Study | Monitoring
```

Backend domains:

| Domain     | Responsibility                                                            |
|------------|---------------------------------------------------------------------------|
| Ingestion  | Parse, chunk, embed, NER (batched GLiNER), graph extraction, summarize    |
| Retrieval  | Hybrid RRF: vector + FTS5 BM25 + Kuzu graph                               |
| LLM        | Cache-first summarization, Q&A, explanation via LiteLLM                   |
| Learning   | Flashcard generation, FSRS scheduling, gap detection                      |
| Monitoring | Phoenix tracing, Langfuse evals, RAG quality metrics                      |

## Tech Stack

| Layer    | Technology                                                          |
|----------|---------------------------------------------------------------------|
| Backend  | Python 3.13, FastAPI, LangGraph, LanceDB, SQLite FTS5, Kuzu, GLiNER, LiteLLM |
| Frontend | React 18, TypeScript 5, Vite 5, shadcn/ui, Sigma.js v3             |

## Quickstart

**Prerequisites**

- [uv](https://docs.astral.sh/uv/) — Python package manager
- Node 20+
- [Ollama](https://ollama.com/) — local LLM server required for Chat and Summarization

```bash
# Install Ollama (macOS)
brew install ollama

# Pull the required model
ollama pull mistral
```

**Start the app**

```bash
git clone <repo-url>

# Terminal 1 — Ollama (must be running before the backend starts)
ollama serve

# Terminal 2 — backend
make backend

# Terminal 3 — frontend
make frontend

# Open in browser
open http://localhost:5173
```

Or start backend + frontend together (Ollama must already be running):

```bash
ollama serve &   # if not already running
make dev
```

For colorized, per-process log output with DEBUG-level ingestion tracing (recommended for development):

```bash
make logs
```

Backend lines appear in cyan `[BACKEND]`, frontend lines in green `[FRONTEND]`. Press Ctrl-C to stop both.

## Running Tests

```bash
# Backend unit tests
make test

# TypeScript type check
cd frontend && npx tsc --noEmit

# All CI checks (lint + tests + build)
make ci
```

Tests are safe to run alongside a live dev backend. `tests/conftest.py`
sets `DATA_DIR` to a temporary directory for the entire test session, so
pytest never touches `~/.luminary` and Kuzu file-lock conflicts cannot occur.

### Integration Tests

Integration tests run the full ingestion pipeline on real public-domain text
fixtures (`time_machine.txt`, `art_of_unix_ch1.txt`) without downloading ML
models. Heavy services are mocked: LiteLLM classification, BGE-M3 embeddings,
and GLiNER entity extraction. Real SQLite FTS5, LanceDB, and Kuzu run in a
temp directory.

```bash
# Integration tests only (slower — ~50s due to LangGraph pipeline)
cd backend && uv run pytest tests/test_integration.py -v

# Run all tests including integration
make test
```

### Full Integration Tests

Full integration tests run the ingestion pipeline against complete public-domain
documents using the **real** BAAI/bge-m3 embedding model and the **real** GLiNER
NER model. LiteLLM classification is still mocked to avoid an Ollama dependency.

These tests live in `tests/test_integration_full.py` and are marked
`@pytest.mark.slow`. They are excluded from `make test` (fast CI path) and must
be run explicitly:

```bash
# Full integration tests (5-10 min on first run due to model downloads)
make test-full

# Equivalent direct invocation
cd backend && uv run pytest tests/test_integration_full.py -v -m slow
```

**Fixtures used** (committed under `tests/fixtures/full/`):
- `time_machine.txt` — full Project Gutenberg text of *The Time Machine* (~185k chars)
- `art_of_unix.txt`  — converted plain text of *The Art of Unix Programming* (~109k chars)

On first run, BGE-M3 and GLiNER models are downloaded into the pytest temp
directory (`DATA_DIR`). Subsequent runs reuse the cache in the same temp path.

**What is asserted:**
- `time_machine.txt`: stage=complete, ≥50 chunks, ≥10 entities, ≥3 search hits for "time traveller"
- `art_of_unix.txt`: stage=complete, ≥100 chunks, ≥15 entities, ≥3 search hits for "Unix philosophy"

## E2E Upload Tests

`tests/test_e2e_upload.py` contains two test flavours:

**`integration_http` (included in `make ci`)**
Uses `ASGITransport` with an in-memory SQLite database and mocked ML services
(no Ollama or model downloads required). Tests the full HTTP upload path:
`POST /documents/ingest` → asyncio background ingestion → `GET /documents/{id}/status`
polling. Runs automatically as part of `make ci`.

**`e2e` (excluded from `make ci`)**
Requires a running backend and Ollama. Start both before running:

```bash
# Terminal 1 — start the backend
make backend

# Terminal 2 — start Ollama
ollama serve

# Terminal 3 — run E2E tests
make test-e2e

# Or point at a custom backend URL
BACKEND_URL=http://my-host:8000 make test-e2e
```

**What is asserted (e2e):**
- `test_upload_and_poll`: file reaches `stage=complete` within 120 s; `progress_pct` increases monotonically
- `test_upload_error_surfaced`: corrupt PDF reaches `stage=error` with a non-empty `error_message`
- `test_status_polling_contract`: `{stage, progress_pct, done, error_message}` schema validated on every poll

## Running Evaluations

Start Langfuse (requires Docker):

```bash
docker compose -f docker-compose.langfuse.yml up -d
```

Run RAGAS evaluations against golden datasets:

```bash
cd evals && uv run python run_eval.py --dataset book --backend-url http://localhost:8000
```

View results in Langfuse at [http://localhost:3000](http://localhost:3000).

### Quality Gates

Run `make eval` after any change to ingestion, chunking, embedding, or retrieval to verify quality has not regressed:

```bash
# Requires: backend running on :8000 (make backend)
make eval
```

`make eval` runs the `book` and `paper` datasets with `--assert-thresholds` and exits 1 if any metric falls below:

| Metric      | Threshold |
|-------------|-----------|
| HR@5        | ≥ 0.60    |
| MRR         | ≥ 0.45    |
| Faithfulness| ≥ 0.65 (LLM scoring only, requires `--model`) |

Each eval run appends a line to `evals/scores_history.jsonl`. The **Monitoring** tab reads this file via `GET /monitoring/eval-history` and renders a sparkline of HR@5 over time per dataset.

## Performance Baselines

Performance regression tests live in `tests/test_performance.py` and are marked
`@pytest.mark.slow`. They use mocked embedder and NER services so no ML models
are required.

```bash
# Run performance tests
make test-perf

# Equivalent direct invocation
cd backend && uv run pytest tests/test_performance.py -v -m slow
```

**What is asserted** (regression guards, not hard SLAs):

| Test                               | Assertion                                    |
|------------------------------------|----------------------------------------------|
| `test_search_latency_p50_p95`      | p50 < 500ms, p95 < 2000ms over 20 queries    |
| `test_ingestion_throughput_...`    | 10 documents complete within 120s            |
| `test_memory_growth_under_500mb`   | RSS growth < 500MB while ingesting 10 docs   |

The goal is to catch 10x regressions (e.g. search taking 30s instead of 300ms).

## Monitoring

Visit the **Monitoring** tab in the app for:

- RAG quality metrics (HR@5, MRR, Faithfulness, Context Precision)
- Ingestion queue status
- Model usage breakdown (local vs cloud)
- Recent evaluation run results

Detailed LLM traces are available in Arize Phoenix at [http://localhost:6006](http://localhost:6006).

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Frontend conventions](docs/FRONTEND.md)
- [Quality scores](docs/QUALITY_SCORE.md)
- [Core beliefs](docs/design-docs/core-beliefs.md)
