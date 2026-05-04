---
description: Luminary architecture overview -- always loaded. Read before making any structural change to the backend or frontend.
---

# Luminary Architecture

## Six-Layer Import Rule (mechanically enforced)

```
Types --> Config --> Repo --> Service --> Runtime --> API
```

- **Types** (`schemas.py`, Pydantic models, enums): zero I/O, zero imports from other layers
- **Config** (`config.py`): singleton `Settings` via `@lru_cache`, reads `.env`
- **Repo**: SQLAlchemy async queries, LanceDB ops, Kuzu Cypher. Reads/writes only.
- **Service**: business logic, orchestrates repos + ML models, implements domain rules
- **Runtime**: LangGraph state machines, background workers, lifespan hooks
- **API** (`routers/`): thin FastAPI handlers -- validate input (Pydantic), call service, return response

**Never import backwards.** A Repo importing a Service is a build failure. A Router containing business logic is a review failure.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend language | Python 3.13 + uv (never pip/Poetry) |
| Web framework | FastAPI + uvicorn (async-first) |
| Workflow routing | LangGraph (not plain LangChain) |
| Embeddings | BAAI/bge-m3 via ONNX Runtime (1024-dim) |
| Vector DB | LanceDB (embedded, Apache Arrow) |
| Keyword search | SQLite FTS5 (BM25) |
| Graph DB | Kuzu (embedded, Cypher, Apache 2.0) |
| Retrieval | RRF = vector + keyword + graph fusion |
| NER | GLiNER (zero-shot, custom types) |
| LLM routing | LiteLLM (Ollama local + cloud providers) |
| Spaced repetition | FSRS (not SM-2) |
| Tracing | Arize Phoenix (local, OpenTelemetry) |
| Frontend | React 18 + TypeScript 5 + Vite 5 |
| UI components | shadcn/ui + Tailwind CSS |
| Knowledge graph viz | Sigma.js v3 + Graphology (WebGL) |
| State | Zustand |
| Data fetching | TanStack Query |
| Desktop packaging | Tauri v1.6 (Phase 5, not yet) |

## Data Stores

- **SQLite** (`~/.luminary/luminary.db`): all structured metadata -- documents, chunks, sections, summaries, flashcards, notes, Q&A history
- **LanceDB**: dense embeddings for chunks (1024-dim) and notes (1024-dim)
- **SQLite FTS5**: `chunks_fts` and `notes_fts` virtual tables for BM25 keyword search
- **Kuzu**: knowledge graph -- Entity, Document, Note nodes + 20+ relationship types

## Navigation Tabs

`Learning | Chat | Viz | Study | Notes | Monitoring`

## Backend Directory

```
backend/app/
  models.py          SQLAlchemy ORM models (single file)
  db_init.py         DDL: CREATE TABLE / CREATE INDEX (run at startup)
  database.py        Engine + session factory
  config.py          Settings (pydantic-settings)
  services/          Business logic (one file per domain)
  routers/           FastAPI routers (one file per domain)
  runtime/           LangGraph graphs, background workers
  workflows/         Ingestion pipeline (LangGraph)
  telemetry.py       Arize Phoenix tracing
backend/tests/       pytest tests (mirror app/ structure)
```

## Frontend Directory

```
frontend/src/
  components/        Reusable components
  pages/             Tab-level components (Learning, Chat, Viz, Study, Notes, Monitoring)
  store/             Zustand stores
  lib/               Utilities (utils.ts, api.ts)
  hooks/             Custom React hooks
```
