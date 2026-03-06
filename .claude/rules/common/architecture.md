# Luminary Architecture Rules

Quick reference for codebase structure. Full details: `docs/ARCHITECTURE.md`.

## Backend Domain Structure

```
backend/app/
  types/        # Pydantic models, enums, TypedDicts — no I/O
  config.py     # Settings singleton via @functools.lru_cache
  repos/        # DB access — SQLAlchemy, LanceDB, Kuzu queries
  services/     # Business logic — orchestrates repos, calls ML models
  runtime/      # LangGraph graphs, background workers, lifespan hooks
  api/          # FastAPI routers — thin, validates input, calls services
  main.py       # App entry point, lifespan context manager
  database.py   # Engine/session factory
```

## Five Backend Domains

| Domain | Services | Key Tech |
|--------|----------|----------|
| Ingestion | ingestion_service, chunking, entity extraction | PyMuPDF, LangGraph, GLiNER |
| Retrieval | retriever, vector_store, keyword_search | LanceDB, SQLite FTS5, Kuzu |
| LLM | summarizer, qa, explainer | LiteLLM, Ollama |
| Learning | flashcard, fsrs_scheduler, gap_detector | fsrs |
| Monitoring | telemetry, eval | Arize Phoenix, Langfuse, RAGAS |

## Frontend Structure

```
frontend/src/
  components/   # Reusable UI — shadcn/ui, Tailwind
  pages/        # Tab-level pages (Learning, Chat, Viz, Study, Monitoring)
  hooks/        # Custom React hooks
  stores/       # Zustand state stores
  lib/          # API clients, utilities
  types/        # TypeScript interfaces
```

## Data Stores

- **SQLite** — documents, sections, chunks, summaries, flashcards, qa_history, eval_runs
- **LanceDB** — chunk_vectors (1024-dim BAAI/bge-m3 embeddings)
- **SQLite FTS5** — chunks_fts (BM25 keyword index, kept in sync with chunks)
- **Kuzu** — Entity nodes, Document nodes, edges (MENTIONED_IN, APPEARS_IN, RELATED_TO)

## Retrieval Pipeline

```
Query → [vector search (LanceDB)] \
        [keyword search (FTS5)]    → RRF merge → diversify → top-k chunks
        [graph traversal (Kuzu)] /
```

## Navigation Tabs

Learning | Chat | Viz | Study | Monitoring
