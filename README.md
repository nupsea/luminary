# Luminary

Luminary is a local-first personal knowledge and learning assistant. It ingests your documents (PDFs, books, papers, conversations, notes, and code), builds a queryable knowledge graph, and turns content into spaced-repetition flashcards -- all running on your machine with no data leaving your device unless you configure a cloud LLM key.

## Features

- **Document ingestion** -- Upload PDFs, plain text, and other formats. Luminary parses, chunks, embeds, and indexes them automatically.
- **Hybrid Contextual search** -- Queries combine vector similarity (`BAAI/bge-m3`, 1024-dim), BM25 keyword search (SQLite FTS5), and graph traversal (Kuzu).
- **Smart Chunking** -- Uses structural splitting (paragraph/sentence boundaries) and **Context Injection** (prepending book/chapter titles to chunks) to improve retrieval accuracy.
- **Parent-Child Retrieval** -- Automatically fetches neighboring chunks during search to provide coherent, high-quality context windows to the LLM.
- **Knowledge graph** -- Entities and relationships are extracted with GLiNER and stored in an embedded graph DB. Explore visually in the Viz tab.
- **Agentic chat** -- Ask questions across your library. The chat graph classifies intent, routes to the right retrieval path, and retries on low-confidence answers.
- **Summaries** -- Executive and detailed summaries generated per document and per section, cached after the first run.
- **Spaced repetition** -- Flashcards generated from document content, scheduled with FSRS (superior to SM-2 in retention accuracy).
- **Notes** -- Markdown notes editor with side-by-side Write/Preview. Notes are searchable alongside your uploaded documents.
- **Dynamic Evaluation** -- RAGAS-based retrieval quality metrics (HR@5, MRR, Faithfulness) with a golden dataset runner. The **Monitoring** tab allows selecting and running any golden dataset (`.jsonl`) found in the `evals/golden/` directory.
- **Local by default** -- Runs entirely on your machine using Ollama. Optimized for performance with 1024-dimensional bge-m3 embeddings via ONNX Runtime and batched vector storage.

## Architecture

```
Types -> Config -> Repo -> Service -> Runtime -> API
         (6-layer dependency rule -- no reverse imports)
```

Backend domains:

| Domain     | Responsibility                                                         |
|------------|------------|
| Ingestion  | Parse, **Hybrid Contextual chunking**, embed, NER (GLiNER), graph, summarize |
| Retrieval  | **Parent-Child RRF**: vector (LanceDB v3) + BM25 (FTS5) + neighbors   |
| LLM        | Cache-first summarization, Q&A, explanation via LiteLLM                |
| Learning   | Flashcard generation, FSRS scheduling, gap detection                   |
| Monitoring | Phoenix tracing, Langfuse evals, **Dynamic RAGAS datasets**            |

Navigation tabs: **Learning | Chat | Viz | Study | Notes | Monitoring**

## Tech Stack

| Layer    | Technology                                                                       |
|----------|----------------------------------------------------------------------------------|
| Backend  | Python 3.13, FastAPI, LangGraph, LanceDB (v3), SQLite FTS5, Kuzu, GLiNER, LiteLLM |
| Frontend | React 18, TypeScript 5, Vite 5, shadcn/ui, Tailwind CSS, Sigma.js v3            |
| Storage  | SQLite (documents, flashcards, history), LanceDB (vectors), Kuzu (graph)         |
| LLM      | Ollama (local, default), OpenAI / Anthropic / Gemini (optional via LiteLLM)      |
| Embedder | `BAAI/bge-m3` (1024-dim via ONNX Runtime, batched inference)                   |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) -- Python package manager
- Node 20+
- [Ollama](https://ollama.com/) -- local LLM server (required for Chat and Summarization)

```bash
# Install Ollama (macOS)
brew install ollama

# Pull the default model
ollama pull mistral
```

## Platform Notes

### macOS Intel (x86_64)

Three core packages — `lancedb`, `onnxruntime`, and `kuzu` — have dropped Intel macOS wheels and have no source distributions on PyPI. None are buildable without major effort on Python 3.13. **Docker is the only practical path.**

Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/) then run:

```bash
make luminary
```

`make luminary` detects Intel Mac automatically, builds the backend into a Linux container (first run takes a few minutes), and wires it to your local Ollama. The frontend still runs natively.

> All other platforms (Linux x86_64/ARM64, macOS Apple Silicon, Windows x86_64) install with no extra steps.

## Quickstart

```bash
git clone <repo-url>
cd luminary

# Install frontend deps (first time only)
cd frontend && npm install && cd ..

# Start Ollama (required for Chat and Summarization)
ollama serve &

# Launch everything with a single command
make luminary
```

`make luminary` starts the backend and frontend, waits for both to be ready, then prints the URL. Open [http://localhost:5173](http://localhost:5173) when it reports ready.

For colorized, per-process log output with DEBUG-level ingestion tracing:

```bash
make logs
```

Backend lines appear in cyan `[BACKEND]`, frontend in green `[FRONTEND]`. Ctrl-C stops both.

## Make Commands

| Command | Description |
|---|---|
| `make luminary` | **Recommended.** Start backend + frontend, wait for readiness, print URL |
| `make dev` | Start backend + frontend together (no readiness wait) |
| `make backend` | Start backend only (port 8000) |
| `make frontend` | Start frontend only (port 5173) |
| `make logs` | Colorized dev log output with DEBUG tracing |
| `make lint` | Run ruff (Python) + tsc type-check (TypeScript) |
| `make test` | Backend unit + integration tests |
| `make test-full` | Full corpus integration tests (slow, real ML models) |
| `make test-concurrent` | Concurrent session tests |
| `make test-perf` | Performance/latency tests |
| `make test-e2e` | E2E upload tests (requires running backend) |
| `make test-book-e2e` | Book ingestion E2E tests |
| `make test-book-content` | Book content retrieval tests |
| `make test-books-all` | Ingest all 3 corpus books, then run all book tests |
| `make smoke` | Smoke tests against backend on :8000 |
| `make eval` | RAGAS quality evals with threshold assertions |
| `make ci` | Full CI: sync deps → lint → layer check → tests → build |

## Running Tests

```bash
# Backend unit + integration tests
make test

# TypeScript type check
cd frontend && npx tsc --noEmit

# All CI checks (lint + type check + tests + build)
make ci
```

Tests use a temporary `DATA_DIR` so they never touch `~/.luminary` and cannot conflict with a live dev backend.

### Integration Tests

Integration tests run the full ingestion pipeline on real public-domain fixtures. Core ML services (BAAI/bge-m3 embeddings, GLiNER NER) use real models; only LiteLLM is mocked. Real SQLite FTS5, LanceDB, and Kuzu run in a temp directory.

```bash
cd backend && uv run pytest tests/test_integration.py -v
```

### Full Integration Tests (slow)

Full corpus integration tests ingest all 3 canonical books (Time Machine, Alice in Wonderland, The Odyssey) with real ML models and verify retrieval quality. First run downloads models (~2-5 min); subsequent runs reuse the cache.

```bash
make test-full
# or: cd backend && uv run pytest tests/test_integration_full.py -v -m slow
```

### E2E Upload Tests

```bash
# Requires backend and Ollama running
make test-e2e

# Point at a custom backend URL
BACKEND_URL=http://my-host:8000 make test-e2e
```

### Performance Tests

```bash
make test-perf
# or: cd backend && uv run pytest tests/test_performance.py -v -m slow
```

Asserts p50 search latency < 500ms, p95 < 2000ms, and RSS growth < 500MB while ingesting 10 documents.

## Running Evaluations

Start Langfuse (requires Docker):

```bash
docker compose -f docker-compose.langfuse.yml up -d
```

Run RAGAS evaluations against the bundled golden datasets:

```bash
cd evals && uv run python run_eval.py --dataset book --backend-url http://localhost:8000
```

You can run any `.jsonl` file in `evals/golden/` by passing its name as the `--dataset`.

### Quality Gates

```bash
# Requires: backend running on :8000
make eval
```

`make eval` runs the `book` and `paper` datasets with `--assert-thresholds` and exits 1 if any metric falls below:

| Metric       | Threshold |
|--------------|-----------|
| HR@5         | >= 0.60   |
| MRR          | >= 0.45   |
| Faithfulness | >= 0.65 (requires `--model`, LLM scoring only) |

## Monitoring

The **Monitoring** tab shows:

- **Dynamic Eval Runner** -- Select any golden dataset and trigger a RAGAS run.
- RAG quality metrics (HR@5, MRR, Faithfulness, Context Precision)
- Ingestion queue status
- Model usage breakdown (local vs cloud)
- Evaluation run history sparklines

Detailed LLM traces are available in Arize Phoenix at [http://localhost:6006](http://localhost:6006).

## Contributing

1. Fork the repo and create a feature branch.
2. Install deps: `cd backend && uv sync` and `cd frontend && npm install`.
3. Run `make ci` before opening a PR -- it must pass cleanly.
4. Keep the 6-layer import rule: Types -> Config -> Repo -> Service -> Runtime -> API. No reverse imports.
5. All LLM calls must go through LiteLLM -- no direct provider SDK imports.
6. New service methods and API endpoints require at least one pytest test.

## License

MIT
