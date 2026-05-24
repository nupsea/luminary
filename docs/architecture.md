---
description: Luminary architecture overview -- always loaded. Read before making any structural change to the backend or frontend.
---

# Luminary Architecture

## Six-Layer Import Rule (mechanically enforced)

```
Types --> Config --> Repo --> Service --> Runtime --> API
```

- **Types** (`schemas/`, `types.py`, Pydantic models, enums): zero I/O, zero imports from other layers
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
| Frontend | React 19 + TypeScript 5.9 + Vite 7 |
| UI components | shadcn/ui + Tailwind CSS 3 + Lucide icons |
| Knowledge graph viz | Sigma.js v3 + Graphology (WebGL) |
| State | Zustand v5 |
| Data fetching | TanStack Query v5 |

## Data Stores

- **SQLite** (`~/.luminary/luminary.db`): all structured metadata -- documents, chunks, sections, summaries, flashcards, notes, Q&A history
- **LanceDB**: dense embeddings for chunks (1024-dim) and notes (1024-dim)
- **SQLite FTS5**: `chunks_fts` and `notes_fts` virtual tables for BM25 keyword search
- **Kuzu**: knowledge graph -- Entity, Document, Note nodes + 20+ relationship types

## Navigation Tabs

**Learner rail (top of sidebar):** `Library | Notes | Study | Ask | Map | Progress`

- `Library` (route `/`) — document grid; landing page. Today-hero strip surfaces due cards or Continue-reading.
- `Notes` (`/notes`) — markdown notes, collections, tags.
- `Study` (`/study`) — flashcards (FSRS), teach-back, collection study dashboard.
- `Ask` (`/chat`) — RAG chat across the library with source citations. Renamed from "Chat" in the design refactor; route name preserved for deep-link / cross-tab event compatibility.
- `Map` (`/viz`) — knowledge graph (Sigma.js entity + relationship view). Renamed from "Viz" for the same reasons.
- `Progress` (`/progress`) — streaks, XP, mastery, review schedule. Uses the Luminary lantern glyph as its nav icon.

**Dev rail (bottom of sidebar):** `Quality | Admin`

- `Quality` (`/quality`) — RAGAS retrieval eval dashboard. Demoted from the learner rail in the design refactor.
- `Admin` (`/admin`) — dev tools, ingestion queue, model usage. Also accessible at `/monitoring` (legacy alias).

## Backend Directory

```
backend/app/
  main.py            FastAPI app factory, router registration, lifespan
  config.py          Settings (pydantic-settings, @lru_cache singleton)
  database.py        Engine + async session factory
  db_init.py         DDL: CREATE TABLE / CREATE INDEX (run at startup)
  models.py          SQLAlchemy ORM models (single file)
  types.py           Cross-layer dataclasses / TypedDicts (no I/O)
  telemetry.py       Arize Phoenix tracing + OpenTelemetry exporters
  schemas/           Pydantic request/response schemas (per domain)
  repos/             Data-access layer (SQLAlchemy queries, LanceDB ops)
  services/          Business logic (one file per domain -- ~45 services)
  routers/           Thin FastAPI handlers (one file per domain -- ~30 routers)
  runtime/           LangGraph chat graph + chat_nodes/ (graph node fns)
  workflows/         Ingestion pipeline (LangGraph) + ingestion_nodes/
  scripts/           One-off maintenance / migration scripts
backend/tests/       pytest tests (mirror app/ structure)
```

## Frontend Directory

```
frontend/src/
  App.tsx            Router, nav rail, Cmd+K, global chat panel, prefetch
  main.tsx           React 19 root
  index.css          Tailwind layers + design tokens (--type-*, .lum-*)
  store.ts, vizStore.ts  Zustand stores (main + knowledge map)
  store/             Additional Zustand slice files
  pages/             Tab-level routes
    Learning.tsx, Learning/              Library (route '/')
    Notes.tsx, Notes/
    Study.tsx, Study/
    Chat.tsx, Chat/                      'Ask' tab
    Viz.tsx, Viz/                        'Map' tab
    Progress.tsx
    Admin.tsx, Quality.tsx, Evals.tsx, Monitoring.tsx (dev surfaces)
  components/
    library/         DocumentCard, FilterBar, SearchBar, UploadDialog, ...
    reader/          PDFViewer, EPUBViewer, DocumentReader, ...
    chat/            Chat session list + message components
    study/           CollectionStudyDashboard, struggling-cards panel, ...
    Teachback/       Teach-back result row + expandable detail
    evals/, goals/   Eval dashboard + goal manager components
    icons/           Custom SVG icon components (LuminaryGlyph)
    ui/              shadcn/ui primitives
    *.tsx            Top-level shared components (~30 files)
  lib/               apiClient, utility functions
  hooks/             Custom React hooks (useDebounce, useReviewNotification, ...)
  types/             Generated openapi types (api.ts)
  assets/            Static assets bundled by Vite
```
