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

## Quickstart

```bash
git clone <repo-url>
cd learning-mate

# Terminal 1 -- Ollama must be running before the backend starts
ollama serve

# Terminal 2 -- backend (installs Python deps via uv on first run)
make backend

# Terminal 3 -- frontend (installs npm deps on first run)
make frontend

# Open in browser
http://localhost:5173
```

Or start backend + frontend together (Ollama must already be running):

```bash
ollama serve &   # if not already running
make dev
```

For colorized, per-process log output with DEBUG-level ingestion tracing:

```bash
make logs
```

Backend lines appear in cyan `[BACKEND]`, frontend in green `[FRONTEND]`. Ctrl-C stops both.

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
