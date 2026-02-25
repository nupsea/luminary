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

| Domain     | Responsibility                                        |
|------------|------------------------------------------------------|
| Ingestion  | Parse, chunk, embed, NER, graph extraction            |
| Retrieval  | Hybrid RRF: vector + FTS5 BM25 + Kuzu graph           |
| LLM        | Summarization, Q&A, explanation via LiteLLM           |
| Learning   | Flashcard generation, FSRS scheduling, gap detection  |
| Monitoring | Phoenix tracing, Langfuse evals, RAG quality metrics  |

## Tech Stack

| Layer    | Technology                                                          |
|----------|---------------------------------------------------------------------|
| Backend  | Python 3.13, FastAPI, LangGraph, LanceDB, SQLite FTS5, Kuzu, GLiNER, LiteLLM |
| Frontend | React 18, TypeScript 5, Vite 5, shadcn/ui, Sigma.js v3             |

## Quickstart

**Prerequisites**

- [uv](https://docs.astral.sh/uv/) — Python package manager
- Node 20+
- [Ollama](https://ollama.com/) with `mistral` pulled: `ollama pull mistral`

**Start the app**

```bash
git clone <repo-url>

# Terminal 1 — backend
make backend

# Terminal 2 — frontend
make frontend

# Open in browser
open http://localhost:5173
```

Or start both together:

```bash
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
