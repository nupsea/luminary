# Luminary

Local-first personal knowledge and learning assistant.

## Setup in 3 commands

```bash
cd backend && uv sync
cd frontend && npm install
make dev
```

## Stack

- **Backend**: Python 3.13, FastAPI, LangGraph, LanceDB, SQLite FTS5, Kuzu
- **Frontend**: React 18, TypeScript 5, Vite 5, shadcn/ui, Tailwind CSS
- **Embeddings**: BAAI/bge-m3 (1024-dim, ONNX Runtime)
- **LLM**: LiteLLM (Ollama local + cloud providers)

## Development

```bash
make dev          # start both backend and frontend dev servers
make ci           # run all quality checks
```

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Frontend conventions](docs/FRONTEND.md)
- [Quality scores](docs/QUALITY_SCORE.md)
