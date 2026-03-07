# Luminary Architecture
<!-- Last updated: 2026-03-06 — added query rewriting note in Retrieval domain -->

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

## Current Implementation Status (as of S81, 2026-03-07)

Phases 1–7 + V2 (through S81) are complete:
- Phase 1 (Core): scaffold, ingestion pipeline, hybrid retrieval, LiteLLM, summarization, Q&A, library UI
- Phase 2 (Understanding): layer linter, doc gardener, Kuzu graph, GLiNER NER, Sigma.js Viz, search, explain, notes
- Phase 3 (Learning): FSRS flashcards, spaced repetition, gap detection, teach-back, progress dashboard
- Phase 4 (Monitoring): Arize Phoenix OTel, Langfuse, RAGAS evals, full Monitoring tab
- Phase 5 (Code+Library): tree-sitter code ingestion, call graph, enhanced library catalog with tags/bulk/pagination
- Phase 6 (S30–S44): dev log, docs, resilience, logging, structured telemetry
- Phase 7 (S45–S54): corpus canon (3 books), diagnostics endpoint, demo review gate, per-book content verification tests
- **V2 (S75–S81)**: Hierarchical knowledge (section summaries + fast-path document summary), agentic chat router with intent classification, confidence-adaptive retry

### V2: Agentic Chat Graph (S75–S81)

The chat pipeline is now a LangGraph StateGraph with intelligent routing instead of a linear function.

**Graph Topology:**
```
classify_node
  → route_node (conditional edge dispatches on intent)
    → [strategy nodes: summary|search|graph|comparative]
      → synthesize_node (LLM call with context packing)
        → confidence_gate_node
          → (high|medium confidence OR retry_attempted=True) → END
          → (low confidence AND first attempt) → augment_node
            → synthesize_node (re-run with augmented context)
            → confidence_gate_node → END
```

**Nodes:**
- **classify_node**: keyword heuristics (5 intents: summary/factual/relational/comparative/exploratory, 0.9-0.8 confidence) with LLM fallback for ambiguous cases
- **route_node**: conditional edge dispatching based on intent
- **Strategy nodes** (run once, write to state):
  - **summary_node**: fetch cached executive summary from SummaryModel, direct answer if found, else fall through
  - **search_node**: hybrid RRF retrieval + chunk augmentation with section summaries from SectionSummaryModel
  - **graph_node**: Kuzu entity relationship context, supplements with 5-chunk grounding retrieval
  - **comparative_node**: dual hybrid retrieval (one per side), interleaved results
- **synthesize_node**: pure context packer (dedup, section grouping, 3k-token budget) → system prompt (intent-aware) → LiteLLM streaming → token accumulation
- **confidence_gate_node**: reads confidence field; routes to augment_node (low confidence + first attempt) or END
- **augment_node**: selects complementary strategy based on primary_strategy, appends context, sets retry_attempted=True

**Context Packing (app/services/context_packer.py):**
- Groups chunks by section_id, sorts by relevance, emits section summary once per group
- Deduplicates at 80% text similarity (longest_common_substring)
- Enforces strict 3k-token budget (word_count * 1.3 approximation)
- Returns assembled context string for LLM input

**Performance (with Ollama local):**
- Section summaries: ~30s for 100 units (Semaphore(10))
- Document summary: ~3min for 100-section books (fast-path using section summaries)
- Q&A response: <3s summary intent, <8s factual intent (hybrid RRF + LLM)

**Test Structure (V2):**
- `test_v2_pipeline.py`: 7 integration tests (section summaries, fast-path, intent routing, library overview)
- `test_v2_ingestion_perf.py`: performance benchmarks (guarded by LUMINARY_PERF_TESTS=1)
- `test_chat_graph.py`, `test_intent_classifier.py`, `test_chat_graph_nodes.py`, `test_context_packer.py`, `test_confidence_retry.py`: unit tests

### Test Structure (Phase 7)
Three slow test suites share a single `all_books_ingested` session fixture (conftest_books.py):
- `test_e2e_book.py` — full pipeline for Time Machine (ingest → retrieve → QA → graph)
- `test_diagnostics.py` — per-store count thresholds for all 3 books via `/diagnostics` endpoint
- `test_book_content.py` — entity/keyword/co-occurrence/semantic verification for all 3 books

Run all three with `make test-books-all` (books ingested exactly once per session).
