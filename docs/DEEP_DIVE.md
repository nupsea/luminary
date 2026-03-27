# Luminary: A Deep Dive into Building a Local-First Knowledge and Learning Assistant

*A technical exploration of architecture, design decisions, workflows, and the engineering philosophy behind Luminary.*

---

## Table of Contents

1. [What Is Luminary?](#what-is-luminary)
2. [The Problem It Solves](#the-problem-it-solves)
3. [Architecture Overview](#architecture-overview)
4. [The Six-Layer Dependency Rule](#the-six-layer-dependency-rule)
5. [Data Stores: A Polyglot Persistence Strategy](#data-stores-a-polyglot-persistence-strategy)
6. [Ingestion Pipeline: From Raw Files to Queryable Knowledge](#ingestion-pipeline-from-raw-files-to-queryable-knowledge)
7. [Document Parsing: A Tiered Strategy](#document-parsing-a-tiered-strategy)
8. [Chunking: Content-Type-Aware Segmentation](#chunking-content-type-aware-segmentation)
9. [Hybrid Retrieval: Vector + Keyword + Graph Fusion](#hybrid-retrieval-vector--keyword--graph-fusion)
10. [The Agentic Chat Graph](#the-agentic-chat-graph)
11. [Context Packing: Fitting the Right Information into the LLM Window](#context-packing-fitting-the-right-information-into-the-llm-window)
12. [Knowledge Graph: Entity Extraction and Disambiguation](#knowledge-graph-entity-extraction-and-disambiguation)
13. [Summarization: A Hierarchical Knowledge Pyramid](#summarization-a-hierarchical-knowledge-pyramid)
14. [The Learning Engine](#the-learning-engine)
15. [The Frontend: Six Tabs, One Application](#the-frontend-six-tabs-one-application)
16. [Observability and Evaluation](#observability-and-evaluation)
17. [Deployment Model](#deployment-model)
18. [Performance Characteristics](#performance-characteristics)
19. [Engineering Philosophy: The Harness Engineering Framework](#engineering-philosophy-the-harness-engineering-framework)
20. [Possible Future Extensions](#possible-future-extensions)
21. [Summary](#summary)

---

## What Is Luminary?

Luminary is a local-first personal knowledge and learning assistant. You feed it documents -- PDFs, books, research papers, code files, conversations, notes -- and it builds a queryable knowledge graph, generates spaced-repetition flashcards, surfaces learning gaps, and lets you have a conversation with your entire library. All of this runs on your machine. No data leaves your device unless you explicitly configure a cloud LLM key.

The system is not a thin wrapper around a chat API. It is a multi-store, multi-model application with an agentic routing pipeline, a hybrid retrieval engine fusing three search strategies, a full spaced-repetition scheduler, and an observability stack that traces every LLM call, retrieval query, and ingestion step. It is designed to be the kind of tool you would build if you took the question "How should I study this material?" seriously and answered it with software engineering.

---

## The Problem It Solves

Most AI-powered reading tools fall into one of two traps. The first is the "chat with your PDF" demo: a vector search over chunked text piped into a single LLM call. It works for a toy example but collapses when you ask a comparative question across two books, or when the answer requires understanding the relationship between entities mentioned in different sections.

The second trap is the cloud-only SaaS model. Your documents are uploaded to a third-party server, processed in someone else's infrastructure, and stored in someone else's database. For personal study materials, proprietary research, or anything you would rather keep private, this is a non-starter.

Luminary avoids both traps. It runs a sophisticated multi-strategy retrieval pipeline locally, stores all data in `~/.luminary`, and degrades gracefully when external services are unavailable. If Ollama is not running, you still get keyword search, entity browsing, and flashcard review. If no cloud API key is configured, the system uses local models for everything.

---

## Architecture Overview

The application is split into a Python backend (FastAPI, async-first) and a React frontend (TypeScript, Vite). They communicate over HTTP and Server-Sent Events (SSE) for streaming.

```
                    Frontend (React 18 + TypeScript 5)
                              |
                         HTTP / SSE
                              |
                    FastAPI (Python 3.13, async)
                              |
        +---------+-----------+----------+---------+
        |         |           |          |         |
    Ingestion  Retrieval    LLM      Learning  Monitoring
    (LangGraph) (RRF)    (LiteLLM)   (FSRS)   (Phoenix)
        |         |           |          |         |
        +----+----+-----------+----+-----+---------+
             |                     |
    +--------+--------+    +------+------+
    | SQLite (ACID)   |    | LanceDB    |
    | + FTS5 (BM25)   |    | (vectors)  |
    +-----------------+    +------------+
             |
    +--------+--------+
    | Kuzu (graph DB) |
    +-----------------+
```

The backend is organized into five product domains -- Ingestion, Retrieval, LLM, Learning, and Monitoring -- each with its own services, models, and API endpoints. The domains share data stores but do not import each other's internals directly. Coordination happens through well-defined service interfaces.

---

## The Six-Layer Dependency Rule

Within each domain, code is organized into six layers with imports flowing strictly forward:

```
Types --> Config --> Repo --> Service --> Runtime --> API
```

- **Types**: Pydantic models, enums, dataclasses. Zero I/O. These define the vocabulary of the system.
- **Config**: A singleton `Settings` object via `@lru_cache`. Reads environment variables and `.env` files at startup. All configuration flows from here.
- **Repo**: Database access. SQLAlchemy async queries, LanceDB operations, Kuzu Cypher queries. Repos know how to read and write, but not what to do with the data.
- **Service**: Business logic. A service orchestrates repos, calls ML models, and implements domain rules. The service layer is where the interesting decisions happen.
- **Runtime**: LangGraph state machines, background workers, and lifespan hooks. The runtime layer wires services into execution flows.
- **API**: FastAPI routers. Thin handlers that validate input (via Pydantic models -- never raw dicts), call a service or runtime, and return a response.

This layering is not a suggestion. It is mechanically enforced by two custom linters (`layer_linter.py` and `boundary_checker.py`) that run in CI. A reverse import -- say, a Repo importing a Service -- fails the build with a remediation message explaining what to fix.

**Why this matters:** When an agent (or a new contributor) reads the codebase, the layering makes the dependency graph predictable. You know that a service file will never import a router, that a type file has no side effects, and that the API layer is always the outermost shell. This predictability reduces the cognitive load of navigating a large codebase.

---

## Data Stores: A Polyglot Persistence Strategy

Luminary uses four data stores, each optimized for a specific access pattern:

### SQLite (Transactional Core)

All structured metadata lives in SQLite: documents, sections, chunks, summaries, flashcards, notes, Q&A history, evaluation runs, and settings. SQLite provides ACID transactions, is embedded (no server), and stores everything in a single file (`~/.luminary/luminary.db`).

Key tables include `documents` (metadata, ingestion status, SHA-256 file hash for dedup), `chunks` (text segments with section references and page numbers), `summaries` (cached per mode: executive, detailed, one-sentence), and `flashcards` (FSRS state, stability, difficulty, due date).

### SQLite FTS5 (Keyword Search)

Two FTS5 virtual tables -- `chunks_fts` and `notes_fts` -- provide BM25 keyword search. FTS5 is SQLite's built-in full-text search engine; it creates an inverted index over token-level terms and scores results by term frequency and inverse document frequency.

A practical lesson learned: UNINDEXED columns in FTS5 virtual tables are unreliable for `WHERE col = :val` queries when the table accumulates many rows. The workaround is to query the shadow content table directly (`notes_fts_content WHERE c1 = :nid`), where `c0`, `c1`, `c2` map to column order from `CREATE VIRTUAL TABLE`.

### LanceDB (Vector Search)

LanceDB stores dense embeddings for chunks and notes. Built on Apache Arrow, it is embedded (no server), supports fast cosine similarity search, and handles incremental upserts efficiently. Vectors are 1024-dimensional, generated by the BAAI/bge-m3 model via ONNX Runtime.

The table schema uses PyArrow native types (`list_(float32(), 1024)`) for vector columns, with additional metadata columns (chunk_id, document_id, section_heading, page) for filtering and attribution.

### Kuzu (Knowledge Graph)

Kuzu is an embedded graph database supporting Cypher queries. It stores the knowledge graph: Entity nodes (with name, type, frequency, and aliases), Document nodes, and multiple edge types:

- **MENTIONED_IN**: Entity is mentioned in Document (with count)
- **CO_OCCURS**: Two entities appear together frequently (with weight and source document)
- **RELATED_TO**: Semantic relationship between entities (with label and confidence)
- **CALLS**: Function call graph for code documents

The graph is traversed during retrieval (the "graph" leg of hybrid search), during chat routing (entity grounding for vague queries), and during gap detection (identifying which concepts the user has and has not explored).

**Why polyglot persistence?** A single store cannot serve all access patterns efficiently. SQLite excels at ACID writes and structured queries but cannot do cosine similarity search. LanceDB excels at vector search but has no full-text indexing. Kuzu excels at multi-hop relationship traversal but is not a general-purpose relational database. By combining all four, each query type routes to the store that handles it best.

---

## Ingestion Pipeline: From Raw Files to Queryable Knowledge

Ingestion is implemented as a LangGraph state machine -- a directed graph where each node transforms the pipeline state and conditional edges route to the next node based on content type.

```
Upload
  |
  v
parse_node          Extract text and sections (PyMuPDF, python-docx, ebooklib)
  |
  v
classify_node       Detect content type: book, paper, tech_book, conversation, code, notes
  |
  +--[audio/video]--> transcribe_node (faster-whisper) --> chunk_node
  |
  v
chunk_node          Split into overlapping segments (content-type-aware sizes)
  |
  v
embed_node          Generate 1024-dim embeddings (BAAI/bge-m3 via ONNX)
  |
  v
entity_extract_node Zero-shot NER (GLiNER) + entity disambiguation
  |
  v
store_node          Persist to SQLite + LanceDB + FTS5 + Kuzu
  |
  v
summarize_node      Section summaries (background, Semaphore(10))
  |                 Document summary fast-path (from section summaries)
  v
complete
```

Progress is tracked in real-time and surfaced in the UI: parsing = 10%, chunking = 40%, embedding = 70%, complete = 100%. The upload dialog stays open until ingestion finishes, so the user always knows what is happening.

Content-type classification uses a heuristic cascade: file extension for audio/video/code, structural patterns for conversations (speaker labels) and papers (abstract, methodology, references), word count and chapter patterns for books, and code-fence density for technical books. A fallback to LLM classification fires only when heuristics are inconclusive.

---

## Document Parsing: A Tiered Strategy

PDF parsing is deceptively difficult. Academic papers use complex font embedding, books have chapter headers at varying indentation levels, and some PDFs encode visualizations as inline form XObjects whose raw stream commands (`0.122 0.467 0.706 rg / /GS0 gs / 11.265 195.264 re`) look like text if you read the file as bytes.

Luminary uses a tiered parsing strategy:

**For PDFs:**
1. **BookParser** tries first: opens the PDF with PyMuPDF, extracts text via `page.get_text()`, and looks for chapter patterns (CHAPTER I, Part 1, etc.). If chapters are found, the document is segmented by chapter boundaries.
2. **Font-size heuristic** runs if BookParser fails: extracts structured text via `page.get_text("dict")`, computes average body font size across all spans, and treats any line with `max_font_size >= body_avg * 1.2` (and length < 120 characters) as a section heading. This approach uses actual font metrics from the PDF structure, producing excellent results for academic papers (Abstract, Introduction, Background, Model Architecture, Results, Conclusion, References -- all correctly identified).

**For text files (TXT, DOCX, Markdown, EPUB):**
1. **BookParser** tries its regex families for chapter patterns.
2. **UniversalParser** runs signature discovery: it probes the first 50,000 characters for repeating structural patterns (numbered sections like `1.1 Introduction`, explicit chapter headers, Roman numeral markers, screenplay cues, chat speaker labels). Each candidate signature is scored by frequency, regularity of spacing, and monotonicity (do numbers actually count up?). The highest-scoring signature above a 0.3 threshold wins.
3. **Format-specific fallback** uses native structure (DOCX paragraphs, Markdown headings, EPUB chapters).

**Why the font-size heuristic is better than regex for PDFs:** PDF text extraction produces flat text where section boundaries are lost. A regex looking for "Introduction" as a standalone line will miss papers that use "1 Introduction" or "I. INTRODUCTION" or any of a dozen other conventions. The font-size heuristic sidesteps this entirely: headings are larger text, and PyMuPDF knows the font size of every span. This is a case where using the richer data available in the source format beats trying to infer structure from flattened text.

---

## Chunking: Content-Type-Aware Segmentation

Not all text should be chunked the same way. A research paper with dense technical content needs smaller chunks (300 tokens) with high overlap (45 tokens) to preserve context across chunk boundaries. A novel can use larger chunks (600 tokens) because narrative prose is less information-dense per token.

| Content Type | Chunk Size (tokens) | Overlap (tokens) | Rationale |
|-------------|-------|---------|-----------|
| Paper | 300 | 45 | Dense; preserve cross-sentence context |
| Book | 600 | 120 | Full paragraphs; narrative continuity |
| Conversation | 450 | 90 | Preserve dialogue turns and speaker flow |
| Tech Book | 500 | 80 | Balance code blocks with surrounding prose |
| Code | 300 | 75 | Function-grained; tree-sitter AST boundaries preferred |

**Context injection** is a critical detail: each chunk is prefixed with `[Document Title > Section Heading]`. This means a chunk from Chapter 3 of "The Time Machine" includes the title and chapter name in its embedding, dramatically improving retrieval accuracy for queries like "What happens in the future in The Time Machine?" that would otherwise match any science-fiction text about the future.

For code files, tree-sitter AST parsing identifies function and class boundaries. Chunks align to these boundaries where possible, and metadata headers (language, file path, line range) are prepended to each chunk. This enables the retrieval pipeline to return function-grained results that include structural context.

---

## Hybrid Retrieval: Vector + Keyword + Graph Fusion

The retrieval pipeline is the core of Luminary's answer quality. It combines three independent search strategies using Reciprocal Rank Fusion (RRF):

```
Query
  |
  +---> Vector Search (LanceDB)    cosine similarity on bge-m3 embeddings
  |
  +---> Keyword Search (FTS5)      BM25 term frequency scoring
  |
  +---> Graph Traversal (Kuzu)     entity co-occurrence + relationship paths
  |
  v
RRF Fusion:  score = SUM( 1 / (k + rank_i) )  for each strategy,  k=60
  |
  v
Diversification:  if >60% of top-k from one section, apply round-robin re-ranking
  |
  v
Parent-Child Augmentation:  fetch +/- 1 neighboring chunks, score at 0.75x parent
  |
  v
Top-N scored chunks returned to caller
```

**Why three strategies?** Each compensates for the other's weaknesses:

- **Vector search** finds semantically similar passages but misses exact keyword matches. A query for "Transformer architecture" might return passages about "attention mechanisms" (semantically close) but miss a passage that uses the exact phrase "Transformer architecture" in a different context.
- **Keyword search** finds exact term matches but misses paraphrases. "Self-attention mechanism" and "query-key-value computation" are the same concept expressed differently; BM25 cannot bridge that gap.
- **Graph search** finds passages connected through entity relationships. If the user asks "How are Transformers related to attention?", the graph can traverse from the "Transformer" entity through CO_OCCURS edges to "attention" and return the chunks where both are mentioned. This is especially valuable for relational and comparative queries.

**RRF fusion** is simple but effective: for each strategy, assign rank 1 to the top result, rank 2 to the second, and so on. The fused score is `sum(1 / (60 + rank))` across all strategies where the chunk appears. The constant `k=60` dampens the advantage of being rank 1 vs rank 2 in any single strategy, so a chunk that appears in all three strategies at moderate ranks can outscore a chunk that is rank 1 in one strategy but absent from the others.

**Diversification** prevents a single section from dominating the results. If more than 60% of the top-k chunks come from one section (or one speaker in a conversation), a round-robin pass redistributes slots across sections in order of their highest-scoring member.

**Parent-child augmentation** expands the context window: for each top-k chunk, the neighboring chunks (by chunk_index within the same section) are fetched and scored at 75% of the parent's score. This ensures the LLM sees coherent multi-paragraph passages rather than isolated fragments.

---

## The Agentic Chat Graph

The chat pipeline is not a simple "retrieve then generate" function. It is a LangGraph StateGraph with conditional routing, confidence-adaptive retry, and intent-specific system prompts.

```
User question
  |
  v
classify_node        Keyword heuristics (0.95-0.80 confidence) + LLM fallback
  |                  Intents: summary | factual | relational | comparative | exploratory | notes
  v
route_node           Conditional edge dispatch based on intent
  |
  +--> summary_node       Fetch cached executive summary from DB
  +--> search_node         Hybrid RRF retrieval + section augmentation
  +--> graph_node          Kuzu entity traversal + grounding retrieval
  +--> comparative_node    Dual retrieval (one per comparison subject)
  +--> notes_node          Hybrid FTS5+semantic search over user notes
  |
  v
synthesize_node      Context packer (dedup, section grouping, 3k-token budget)
  |                  + intent-specific system prompt
  |                  + LiteLLM streaming via SSE
  v
confidence_gate_node
  |
  +--[high | medium | already retried]--> END
  |
  +--[low + first attempt]--> augment_node
                                |
                                v
                              Select complementary strategy
                              (if primary was search, try graph; if graph, try broader search)
                                |
                                v
                              synthesize_node (re-run with merged context)
                                |
                                v
                              confidence_gate_node --> END
```

**Intent classification** is deliberately two-tiered. Fast keyword heuristics handle unambiguous queries (a question starting with "Summarize" routes to summary; one mentioning two named entities routes to comparative). For ambiguous queries, an LLM call classifies the intent. The heuristic layer runs in under 10ms and catches 80%+ of queries; the LLM fallback adds a few hundred milliseconds but is more nuanced.

**Query rewriting** enriches the question with entity names from Kuzu. If the user asks "What did he do after arriving?", the rewriter looks up recently discussed entities and may expand the query to "What did Odysseus do after arriving in Ithaca?". This grounding step is non-fatal -- if Kuzu is empty or the lookup fails, the original query proceeds unchanged.

**Confidence-adaptive retry** is the key differentiator from a single-pass RAG pipeline. After the LLM generates an answer, the confidence gate evaluates whether the answer is high, medium, or low confidence. If low confidence on the first attempt, the augment node selects a complementary retrieval strategy (e.g., if the primary strategy was keyword search, try graph traversal), appends new context, and re-synthesizes. This prevents the common failure mode where a single retrieval strategy misses the relevant passage and the LLM confabulates.

**Streaming** is implemented via SSE. The synthesize node prepares the prompt and context; the router handler calls LiteLLM's async streaming API and yields tokens as `data:` events. The final event includes structured metadata: citations (section heading, page number, excerpt), confidence level, and the retrieval strategy used. The frontend accumulates tokens in real-time and renders the answer with citation chips.

---

## Context Packing: Fitting the Right Information into the LLM Window

The context packer is the bridge between retrieval and generation. Its job is to assemble the most relevant, non-redundant context from retrieved chunks within a strict token budget (default: 3,000 tokens).

**The algorithm:**

1. **Group** chunks by section. Chunks from the same section are clustered together.
2. **Sort** section groups by the maximum relevance score of any chunk in the group. The most relevant section appears first.
3. **Emit** a section header (heading + summary, if available) once per group. This orients the LLM to the section's topic without repeating context.
4. **For each chunk in the group:**
   - Compute Longest Common Substring (LCS) similarity against all previously emitted chunks.
   - If similarity exceeds 80% (near-duplicate), skip the chunk.
   - Otherwise, emit the chunk and deduct its token count from the budget.
5. **Stop** when the token budget is exhausted. The first chunk is always emitted even if it alone exceeds the budget (then truncated to fit).

**Near-duplicate detection** uses a dynamic programming LCS algorithm on the first 300 characters of each chunk pair. The ratio `lcs_length / max(len(a), len(b))` must exceed 0.8 to be considered a duplicate. This catches the common case where overlapping chunks contain 90% identical text due to the chunking overlap window.

**Token counting** uses LiteLLM's `token_counter()` (which wraps tiktoken) for exact counts, with a graceful fallback to `word_count * 1.3` for unknown or local models.

**Per-document diversity** (for scope=all queries): when searching across the entire library, the packer caps at 2 chunks per document. This prevents a single document with high-similarity passages from consuming the entire context window and ensures the LLM sees material from multiple sources.

---

## Knowledge Graph: Entity Extraction and Disambiguation

The knowledge graph is built during ingestion and queried during retrieval and chat routing. It provides a structured representation of the entities and relationships within the user's document library.

### Entity Extraction (GLiNER)

GLiNER is a zero-shot named entity recognition model. Unlike traditional NER models trained on a fixed label set, GLiNER accepts arbitrary entity type labels at inference time. Luminary uses 13 entity types:

**General:** PERSON, ORGANIZATION, PLACE, CONCEPT, EVENT, TECHNOLOGY, DATE

**Tech-specific:** LIBRARY, DESIGN_PATTERN, ALGORITHM, DATA_STRUCTURE, PROTOCOL, API_ENDPOINT

Extracted entities pass through a multi-layer noise filter:
- Pronouns (I, me, my, this, that) are rejected
- Possessive openers ("his father", "my house") are rejected
- Generic nouns without proper modifiers ("city", "company") are rejected
- Tech vocabulary ("class", "function", "method") is rejected for tech entity types
- Date patterns must match specific formats (years 1000-2029, month names, ordinals)
- For large documents (>30 chunks), single-occurrence entities are filtered out

### Entity Disambiguation

Surface-form variants are a persistent problem: "Holmes", "Sherlock Holmes", and "Mr. Holmes" are the same entity but appear as three separate extractions. The EntityDisambiguator canonicalizes them:

1. **Honorific stripping**: Remove leading titles (Mr., Dr., Sir, Prof., etc.) and lowercase. Note: "Sr." is deliberately excluded -- "Sr. Holmes" is not the same as "Holmes" in all contexts.

2. **Three-rule matching** (same entity type only, first match wins):
   - **Rule A (Exact)**: stripped forms are identical
   - **Rule B (Substring)**: one stripped form is a substring of the other; the longer form wins as canonical
   - **Rule C (Token Overlap)**: two or more shared tokens; the longer form wins

3. **Two-pass batch processing**: Pass 1 builds a stable pool by processing all names and evicting shorter canonicals when longer variants arrive. Pass 2 assigns final canonical resolutions using the stable pool. This ensures processing order does not determine which canonical wins.

The result: "Mr. Sherlock Holmes", "Sherlock Holmes", "Holmes", and "Mr. Holmes" all resolve to the canonical "Sherlock Holmes". Aliases are stored in the Kuzu Entity node's `aliases` column (pipe-delimited), and the canonical name is used as the MERGE key for stable entity IDs across re-ingestions.

---

## Summarization: A Hierarchical Knowledge Pyramid

Summarization is pre-computed during ingestion and cached in SQLite. This means summary display is instant (no LLM call on open) -- a critical UX property for a local application where LLM latency can be 3-10 seconds.

**Three levels:**

1. **Section summaries**: Each qualifying section (preview >= 200 characters) gets a 1-2 sentence summary generated in parallel (Semaphore(10) for concurrency). Stored in `SectionSummaryModel`.

2. **Document summaries**: Three modes, each generated from section summaries (not raw chunks):
   - `one_sentence`: 30 words or fewer, single-sentence gist
   - `executive`: 3-5 overarching themes or arguments
   - `detailed`: Per-section summaries preserving heading structure

3. **Library overview**: On-demand synthesis across all documents, using document-level executive summaries as input.

**The fast-path optimization**: Traditional map-reduce summarization requires (a) chunking the entire document, (b) summarizing each chunk batch (the "map" step), (c) concatenating batch summaries, and (d) a final reduction. For a 100-section book, this means dozens of sequential LLM calls and can take 15+ minutes.

The fast path short-circuits this: if section summaries already exist (they do -- they were generated during ingestion), use them directly as input to the mode-specific LLM call. One call, not dozens. A 100-section book summarizes in under 3 minutes instead of 15+.

**Cache-first strategy**: `GET /summarize/{id}/cached` returns all stored summaries instantly (no LLM). `POST /summarize/{id}` checks the cache first; on cache hit, it returns the cached content as a single SSE event. On cache miss, it generates, stores, and streams. The map-reduce intermediate is also cached (pseudo-mode `_map_reduce`), so even an on-demand request for a new mode skips the expensive map step.

---

## The Learning Engine

Luminary is not just a reading tool. It is a learning tool. Three services work together to help the user internalize the material:

### FSRS Spaced Repetition

Flashcards are scheduled using the FSRS-4.5 algorithm, which predicts retention with 95%+ accuracy (vs 77% for the traditional SM-2 algorithm used by Anki). Each card tracks:

- **Stability**: Resistance to forgetting (higher = longer retention intervals)
- **Difficulty**: Predicted future forgetting curve (affects interval growth rate)
- **State**: learning, review, relearning, or new
- **Due date**: Earliest review date (cards not yet due are hidden)

After each review (user rates: Again / Hard / Good / Easy), the FSRS scheduler updates stability and difficulty, computes the next due date, and persists the state. The system also tracks reps (total reviews) and lapses (times the user rated "Again"), which surface in the study progress dashboard.

### Gap Detection

The GapDetectorService identifies concepts from a document that are absent or under-covered in the user's notes:

1. Fetch user notes and build a query string from the first 200 characters
2. Retrieve top-k document chunks via hybrid RRF
3. Call LLM with a structured prompt: "You are a learning gap analyst. Given these notes and these book passages, identify concepts from the passages that are absent from the notes."
4. Return a GapReport: gaps (missing concepts), covered (well-addressed concepts), and weak (covered but poorly mastered based on flashcard performance)

Gap severity is weighted by Bloom taxonomy level and FSRS stability, so a gap in a foundational concept with low flashcard retention ranks higher than a gap in an advanced topic the user has not yet studied.

### Feynman Technique (Socratic Tutoring)

The FeynmanService implements the Feynman technique as an interactive chat mode:

1. The user selects a concept and a document section
2. The system generates a Socratic opening question based on the section content
3. The user explains the concept in their own words
4. The tutor evaluates the explanation, identifies misunderstandings, and asks one targeted follow-up question (never giving the answer directly)
5. At session end, identified gaps can be converted to flashcards

This is teach-back learning automated: the user proves their understanding by explaining, and the system probes where that understanding breaks down.

---

## The Frontend: Six Tabs, One Application

The frontend is a single-page React application with six primary tabs, each serving a distinct phase of the learning workflow:

### Learning Tab
The main document library. Two-column layout: document list with filters and search on the left, document reader on the right. The reader includes a hierarchical section outline, three summary modes (executive, detailed, one-sentence), an explanation sidebar with four modes (simple, detailed, concept, comparison), and a glossary tab. Text selection triggers a floating toolbar with explain, note, and flashcard actions.

### Chat Tab
Conversational Q&A with scope selector (single document, all documents, or selected documents). Responses stream in real-time via SSE with inline citations (section heading, page number, clickable excerpt). The chat graph topology (described above) is invisible to the user -- they just ask a question and get an answer.

### Viz Tab
WebGL knowledge graph visualization using Sigma.js v3 and Graphology. Entity nodes are colored by type, edges show co-occurrence and relationship labels. Users can filter by entity type, search for specific entities, and switch to a code call-graph view for ingested source files. Handles 10,000+ nodes smoothly via GPU-accelerated rendering.

### Study Tab
Flashcard management and study sessions. Generate flashcards from any document or section, review them with FSRS scheduling (Again / Hard / Good / Easy buttons), and track progress via Recharts visualizations (retention curve, mastery heatmap, streak calendar). A weak areas panel shows gap detection results and confusion signals (concepts the user has asked about repeatedly).

### Notes Tab
Personal notes editor with side-by-side Write (Markdown textarea) and Preview (rendered Markdown). Notes are organized by group and tag, searchable via hybrid FTS5+semantic search (debounced at 300ms). Gap detection compares notes against book content to surface under-explored topics.

### Monitoring Tab
System health and quality metrics. Shows Ollama availability, Phoenix tracing status, RAG quality charts (HR@5, MRR, Faithfulness with threshold lines), model usage breakdown, ingestion queue status, recent traces, and evaluation run history. Each section fetches independently -- if one endpoint fails, the others still render.

**Architectural patterns:**
- All tabs are lazily loaded (React.lazy + Suspense) to minimize initial bundle size
- Navigation hover triggers TanStack Query prefetch for the destination tab's data
- All API state is managed through TanStack Query (staleTime: 60s, no refetch on window focus)
- Global UI state (active document, LLM mode, library view) is managed through Zustand
- All API responses are validated at the boundary with Zod schemas

---

## Observability and Evaluation

### Arize Phoenix (Tracing)

Every LLM call, retrieval query, and ingestion step is traced via OpenTelemetry. Phoenix runs as an in-process server on port 6006, storing traces persistently in `~/.luminary/phoenix/`. Custom span types include:

- **Chain spans** for LangGraph nodes and service orchestration
- **Retriever spans** for vector/keyword/graph search with chunk count and latency
- **LLM spans** (auto-instrumented via LiteLLMInstrumentor) with messages, token counts, and model name

### RAGAS Evaluation

Retrieval quality is evaluated against golden datasets (`evals/golden/*.jsonl`). Each entry includes a question, expected answer, and a `context_hint` substring that must appear in the retrieved context for a "hit". Metrics:

| Metric | Threshold | What It Measures |
|--------|-----------|-----------------|
| HR@5 | >= 0.60 | Does the relevant passage appear in the top 5 results? |
| MRR | >= 0.45 | How high does the relevant passage rank? |
| Faithfulness | >= 0.65 | Is the answer grounded in the retrieved context? |

These thresholds are CI gates (`make eval` exits non-zero on failure), not just reports. The Monitoring tab allows triggering eval runs from the UI and displays results as color-coded rows (green/amber/red).

The golden dataset currently covers 70 entries across three canonical books: The Time Machine (30), Alice in Wonderland (20), and The Odyssey (20). All context_hint passages are verified against the actual source texts.

---

## Deployment Model

Luminary is a **local-first desktop application**:

```
User's machine
  |
  +-- Ollama (local LLM server, default: mistral)
  |
  +-- Luminary Backend (FastAPI, uvicorn, port 8000)
  |     |
  |     +-- ~/.luminary/
  |           +-- luminary.db       (SQLite: all structured data)
  |           +-- vectors/          (LanceDB: embeddings)
  |           +-- graph.kuzu        (Kuzu: knowledge graph)
  |           +-- raw/              (uploaded file copies)
  |           +-- models/           (bge-m3, GLiNER model cache)
  |           +-- phoenix/          (trace storage)
  |
  +-- Luminary Frontend (Vite dev server or Tauri desktop app, port 5173)
```

**Prerequisites:**
- Python 3.13 with uv (package manager)
- Node 20+
- Ollama with at least one model pulled (`ollama pull mistral`)

**Startup:**
```bash
ollama serve        # Terminal 1
make dev            # Terminal 2 (starts both backend and frontend)
```

**All data stays local.** The backend binds to `127.0.0.1:8000` (not `0.0.0.0`). CORS allows only localhost origins. No authentication is required in v1 (single-user local app). API keys are stored in SQLite (plaintext v1 -- OS keychain migration planned).

**Cloud LLM is opt-in.** If the user configures an OpenAI, Anthropic, or Google API key, LiteLLM routes requests to the cloud provider. Otherwise, all LLM calls go to Ollama. The system degrades gracefully when Ollama is offline: search, entity browsing, and flashcard review still work; features requiring LLM (summarization, chat, flashcard generation) return HTTP 503 with an actionable message ("Ollama is unreachable. Start it with: `ollama serve`").

**Desktop packaging** via Tauri (v1.6) is planned for Phase 5. Tauri wraps the frontend in a native window and bundles the backend as a sidecar process, producing a single installable application.

---

## Performance Characteristics

Performance targets are defined as SLOs and enforced in CI:

| Operation | Target | Achieved |
|-----------|--------|----------|
| Ingestion pipeline (p95) | < 30s | parse -> entity_extract |
| NER extraction (p95) | < 3 min | per 500 chunks (batched) |
| Summary display (cached) | < 200ms | cache hit, single SSE event |
| Summary display (on-demand) | < 5 min | cache miss, map-reduce |
| Q&A response (p95) | < 3s | end-to-end (with Ollama) |
| Embedding batch (p95) | < 60s | per 100 chunks |
| Flashcard generation (p95) | < 5s | per document |
| Hybrid search (p95) | < 500ms | RRF query |

**Key optimizations:**
- Embedding uses ONNX Runtime for CPU inference (batch size 128, normalize in-place)
- GLiNER uses `batch_predict_entities()` for single-pass NER (4-6x faster than per-item loop)
- Section summaries run with Semaphore(10) for parallelism without overwhelming local LLM
- Context packer uses LCS on first 300 chars only (O(n^2) but n is small)
- LanceDB vector search is sub-5ms (in-process, no network hop)
- FTS5 BM25 search is sub-10ms (SQLite in-process, inverted index)
- Kuzu graph traversal is sub-20ms (in-process, compiled Cypher)

**Memory:** Performance tests assert RSS growth < 500MB while ingesting 10 documents, ensuring the application stays within reasonable bounds on a laptop.

---

## Engineering Philosophy: The Harness Engineering Framework

Luminary's engineering practices are codified in 25 "golden principles" derived from the OpenAI Harness Engineering framework. A few of the most consequential:

**Repository is the system of record.** All architectural decisions, design choices, patterns, and conventions live as versioned Markdown in `docs/`. If it is not in the repo, it does not exist. This is critical for agent-assisted development: an AI agent has no memory between sessions, so the repository must contain everything it needs to make correct decisions.

**Enforce invariants mechanically.** The project has 21 mechanically enforced invariants: no pip (only uv), no direct LLM SDK imports (only LiteLLM), no raw dicts at API boundaries (only Pydantic models), no `print()` in production code (only structured logging), TypeScript strict mode, and more. Each invariant is checked by either a CI linter, a pre-commit hook, or a Claude Code PreToolUse hook. Violation messages include remediation instructions.

**Tests must use real artifacts at real scale.** Integration tests ingest full, untruncated public-domain books with real ML models (BAAI/bge-m3, GLiNER). Only LiteLLM is mocked (to avoid requiring Ollama in CI). Golden datasets for evaluation are grounded in actually ingested content with verifiable context passages.

**Quality metrics are CI gates, not reports.** HR@5, MRR, and Faithfulness have enforced minimum thresholds. `make eval` exits non-zero when any metric falls below its threshold. A metric that cannot fail is not a metric.

**Pure functions for core domain logic.** Response parsing, retrieval scoring, RRF fusion, diversification, and text transformations are all pure functions: no I/O, no network calls, same output for same inputs. This makes them testable with simple `assert` statements and no fixture setup.

---

## Possible Future Extensions

Based on the current architecture and the planned stories in `prd-v2.json`:

### Near-term (architected, stories written)

- **Note semantic search (S91)**: Hybrid FTS5+vector search over user notes, matching the same RRF strategy used for document chunks -- already implemented.
- **Cross-document concept linking (S141)**: Identify when two documents discuss the same concept under different names (e.g., "attention mechanism" in one paper and "self-attention" in another). SAME_CONCEPT edges in Kuzu with confidence and contradiction tracking.
- **Image enrichment (S134)**: Extract diagrams and figures from PDFs, generate text descriptions via vision model (LLaVA), and create searchable embeddings for visual content.
- **Prerequisite detection (S117)**: Automatically identify concept dependencies (A must be understood before B) using graph structure and LLM analysis. PREREQUISITE_OF edges in Kuzu for learning path generation.
- **Study path generation**: Sequence documents and sections into an optimal learning order based on prerequisite graph, FSRS mastery levels, and gap detection results.

### Medium-term (architecturally compatible)

- **Multi-modal ingestion**: YouTube video transcription (yt-dlp + faster-whisper) is already scaffolded. Podcast ingestion, slide deck parsing, and handwritten note OCR would follow the same pipeline with format-specific parse nodes.
- **Collaborative knowledge bases**: Multiple users sharing a Luminary instance with access controls. Requires authentication (not present in v1), per-user data isolation, and conflict resolution for shared entities.
- **Mobile companion**: A read-only mobile app for flashcard review and note browsing. The backend API is already HTTP-based; a React Native or Flutter frontend could consume it directly.
- **Export and interop**: Export flashcards to Anki format, knowledge graphs to Neo4j/GraphML, and summaries to Markdown or Notion. The data is already structured; export is a serialization problem.

### Long-term (would require architectural evolution)

- **Federated knowledge graphs**: Connect multiple Luminary instances to share entity relationships across users or organizations. Would require a gossip protocol or central coordination service.
- **Active learning**: The system actively suggests what to read next based on gap detection, prerequisite analysis, and calendar availability. Would require a planning agent that reasons over the user's learning state.
- **Fine-tuned local models**: Use the user's Q&A history and flashcard performance as training signal to fine-tune the local LLM for their specific domain. Would require PEFT/LoRA infrastructure and careful evaluation to prevent catastrophic forgetting.

---

## Summary

Luminary is a case study in what happens when you take the local-first constraint seriously and build a real application around it. Every design decision -- polyglot persistence, hybrid retrieval, agentic routing, hierarchical summarization, spaced repetition -- flows from two constraints: (1) all data stays on the user's machine, and (2) the system must be genuinely useful for learning, not just for querying.

The result is an application that is more complex than a typical RAG demo but earns that complexity by solving real problems: comparative queries across documents, learning gap identification, confidence-adaptive retry, entity disambiguation, and structured spaced repetition. Each component has a clear value proposition, and the architecture ensures they compose without creating an unmaintainable tangle.

The engineering philosophy -- mechanical invariant enforcement, repository as system of record, real artifacts at real scale -- is as much a part of the system as the code itself. It is what makes the codebase navigable by both humans and AI agents, and what keeps quality from degrading as the system grows.
