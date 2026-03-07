# Quality Score — Luminary

Last Updated: 2026-03-07 — V2 (S75-S80): agentic chat router, section summarization, context packing
Previous milestone: 2026-03-06 — S58 query rewriting, S60 chapter/speaker sidebar

Updated by ralph after each phase. Grades: A (complete), B (mostly done), C (partial), D (minimal), F (not started).

**Grade policy**: Ralph may promote a domain to B based on story completion. Promotion to A requires either a passing human demo-review gate OR a passing `make eval` run with all thresholds met. Self-reported A grades without one of these are provisional.

| Domain          | Implemented | Tested       | Documented   | Quality Grade |
|-----------------|-------------|--------------|--------------|---------------|
| Ingestion       | yes         | yes          | yes          | A             |
| Summarization   | yes         | yes          | yes          | A             |
| Q&A             | yes         | yes          | yes          | A             |
| Knowledge Graph | yes         | yes          | partial      | B             |
| Explain / Notes | yes         | yes          | partial      | B             |
| Search          | yes         | yes          | partial      | B             |
| Learning Engine | yes         | yes          | partial      | B             |
| Study Mode      | yes         | yes          | partial      | B             |
| Monitoring      | yes         | yes          | partial      | B             |
| Code Ingestion  | yes         | yes          | partial      | B             |
| Dev Tooling     | yes         | n/a          | yes          | A             |

## Notes

### Phases 1–5 + S30 completion summary (as of S30)

**Ingestion (A)**: v2: section-level summarization, fast-path document summary, sub-5min for Iliad. LangGraph pipeline fully wired — parse, classify, chunk, embed (BGE-M3 + LanceDB), keyword index (SQLite FTS5), NER via GLiNER with Kuzu graph entity extraction. Code ingestion added (S27) with tree-sitter call graph extraction. Library catalog enhanced with tags, bulk actions, and pagination (S28). NER upgraded to `batch_predict_entities` (4–6× speedup on CPU). Summarize node decoupled as fire-and-forget background task with strong asyncio task reference to prevent GC mid-run. SHA-256 dedup on upload with backfill of missing summaries on re-upload. Section-aware summarization (S75): SectionSummaryModel stores inline + full summaries, parallel summarization nodes for sub-5min pipeline on 100KB+ documents.

**Summarization (A)**: Cache-first, ingestion-time pre-generation. `one_sentence`, `executive`, `detailed` pre-generated as background task after ingestion. Map-reduce intermediate stored as `_map_reduce` pseudo-mode — shared across all modes and subsequent on-demand requests. `GET /summarize/{id}/cached` returns all stored summaries on document open (instant, no LLM). `POST /summarize/{id}` is cache-first; cache hit returns full content as a single SSE event. `conversation` mode still on-demand but skips map step if `_map_reduce` cached.

**Q&A (A)**: v2 agentic router: intent classification, 4 strategy nodes, section-aware context packing. Hybrid RAG (RRF vector + keyword + graph) via HybridRetriever. Chat tab with streaming, citations, confidence. Phoenix tracing wired. Query rewriting: vague-reference pronouns resolved via Kuzu entity lookup before retrieval (S58). Message routing via intent classification (is_search, is_clarify, is_explore, is_chitchat) with specialized nodes for each (S76–S80).

**Knowledge Graph (B)**: Kuzu schema + KuzuService (S15a). Entity extraction wired into ingestion (S15b). Sigma.js Viz tab with force-layout, entity-type filter, node search, click popover, edge tooltip (S16a/b). Call graph view added (S27).

**Explain / Notes (B)**: POST /explain SSE (4 modes) + POST /glossary (S18a). FloatingToolbar + ExplanationSheet + Glossary tab in DocumentReader (S18b). Notes CRUD backend (S19a). Inline NoteEditor in section list + /notes standalone route (S19b).

**Search (B)**: GET /search hybrid backend (S17a). Cmd+K SearchDialog + /search sidebar (S17b).

**Learning Engine (B)**: FSRS-4.5 algorithm (S20a). FlashcardService + generate/review/export endpoints (S20a). Study tab with session management (S21a). Teach-back mode backend: POST /study/teachback/{id}, score LLM, misconception tracking (S21b). Gap detection endpoint GET /study/gaps/{id} with fragility score (S22a). Study stats + history endpoints (S23a).

**Study Mode (B)**: StudySession component with FSRS rating buttons and flip animation (S21a). Weak areas panel + teach-back UI in Study tab (S22b). ProgressDashboard with retention curve, mastery heatmap, streak calendar (S23b).

**Monitoring (B)**: Arize Phoenix OTel instrumentation for Q&A, summarization, retrieval, and all ingestion nodes (S24a). GET /monitoring/traces + Monitoring tab traces table with detail drawer (S24b). Langfuse integration for LLM call logging (S25a). RAGAS evaluation runner + golden datasets + eval runs storage (S25b). Full Monitoring tab dashboard: system status, RAG quality charts, model usage, ingestion queue, traces, eval runs (S26).

**Code Ingestion (B)**: tree-sitter AST parsing for Python/JS/TS/Go/Rust (S27). Function/class boundary chunking. Kuzu CALLS edge table for call graph. Viz tab call graph toggle.

**Dev Tooling (A)**: Colorized dev log script (S30) — `make logs` starts backend+frontend with cyan/green line prefixes, LOG_LEVEL=DEBUG, awk fflush() for real-time output, SIGINT forwarding.
