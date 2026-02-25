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

## Running Tests

```bash
# Backend unit tests
make test

# TypeScript type check
cd frontend && npx tsc --noEmit

# All CI checks (lint + tests + build)
make ci
```

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
