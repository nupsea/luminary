# Luminary Architecture

## Top-Level Domain Map

The backend is organized into 5 product domains:

| Domain      | Responsibility                                             | Key Packages              |
|-------------|-----------------------------------------------------------|---------------------------|
| Ingestion   | Document parsing, chunking, embedding, graph extraction   | PyMuPDF, LangGraph, GLiNER |
| Retrieval   | Hybrid RRF search (vector + keyword + graph)              | LanceDB, SQLite FTS5, Kuzu |
| LLM         | Summarization, Q&A, explanation via LiteLLM               | LiteLLM, Ollama            |
| Learning    | Flashcard generation, FSRS scheduling, gap detection      | fsrs                       |
| Monitoring  | Tracing, evaluation, quality metrics                      | Arize Phoenix, Langfuse, RAGAS |

## 6-Layer Dependency Rule

Within each domain, imports flow **forward only**:

```
Types → Config → Repo → Service → Runtime → API
```

- **Types** (`app/types/`): Pydantic models, enums, dataclasses. No imports from other layers.
- **Config** (`app/config.py`): Settings via pydantic-settings. May import Types only.
- **Repo** (`app/repos/`): Database access (SQLAlchemy, LanceDB, Kuzu). Imports Types + Config.
- **Service** (`app/services/`): Business logic. Imports Repo + Types + Config.
- **Runtime** (`app/runtime/`): LangGraph graphs, long-running workers. Imports Service + all below.
- **API** (`app/api/`): FastAPI routers. Imports Runtime/Service + all below. No reverse imports.

**Cross-cutting concerns** (auth, telemetry, feature flags) enter through explicit Providers
injected via FastAPI `Depends()`.

## Package Layout

```
backend/
  app/
    api/          # FastAPI routers (API layer)
    runtime/      # LangGraph graphs, background workers (Runtime layer)
    services/     # Business logic (Service layer)
    repos/        # DB access — SQLAlchemy, LanceDB, Kuzu (Repo layer)
    types/        # Pydantic models, enums (Types layer)
    config.py     # Settings (Config layer)
    main.py       # FastAPI app, lifespan, middleware
    database.py   # SQLAlchemy engine + session factory
    models.py     # SQLAlchemy ORM models
    db_init.py    # Table creation, FTS5 virtual table

frontend/
  src/
    pages/        # One file per tab: Learning, Chat, Viz, Study, Notes, Monitoring
    components/   # Reusable UI components (reader/, library/, FloatingToolbar, etc.)
    hooks/        # Custom React hooks (useDebounce)
    lib/          # Utility functions (cn, etc.)
    store.ts      # Zustand global state

evals/            # RAGAS evaluation scripts and golden datasets
docs/             # System of record (Harness Engineering)
```

## Data Flow: Ingestion

```
User uploads file
  → API layer receives multipart upload
  → Service: detect content type (PDF/DOCX/TXT/Markdown/code)
  → LangGraph ingestion graph:
      Node 1: Parse (PyMuPDF / unstructured.io)
      Node 2: Chunk (RecursiveCharacterTextSplitter, type-aware sizes)
      Node 3: Embed (BAAI/bge-m3, ONNX, 1024-dim)
      Node 4: NER (GLiNER zero-shot)
      Node 5: Store (LanceDB vectors + SQLite metadata + Kuzu entities)
```

## Data Flow: Retrieval (Hybrid RRF)

```
Query text
  → Embed query (bge-m3)
  → Vector search: LanceDB cosine similarity (top-k)
  → Keyword search: SQLite FTS5 BM25 (top-k)
  → Graph search: Kuzu entity traversal (top-k)
  → RRF fusion: score = Σ 1/(k+rank_i), k=60
  → Re-rank and return top-N chunks
```

## Current Implementation Status (as of S30, 2026-02-25)

All 30 stories through S30 are complete. Phases 1–5 fully implemented:
- Phase 1 (Core): scaffold, ingestion pipeline, hybrid retrieval, LiteLLM, summarization, Q&A, library UI
- Phase 2 (Understanding): layer linter, doc gardener, Kuzu graph, GLiNER NER, Sigma.js Viz, search, explain, notes
- Phase 3 (Learning): FSRS flashcards, spaced repetition, gap detection, teach-back, progress dashboard
- Phase 4 (Monitoring): Arize Phoenix OTel, Langfuse, RAGAS evals, full Monitoring tab
- Phase 5 (Code+Library): tree-sitter code ingestion, call graph, enhanced library catalog with tags/bulk/pagination
- Phase 6 (S30): colorized dev log script (`make logs`)
