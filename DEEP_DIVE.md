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
15. [The Frontend: A 72px Nav Rail, Seven Learner Surfaces, Three Dev Surfaces](#the-frontend-a-72px-nav-rail-seven-learner-surfaces-three-dev-surfaces)
16. [Observability and Evaluation](#observability-and-evaluation)
17. [Deployment Model](#deployment-model)
18. [Model Selection: One Registry, Three Bands](#model-selection-one-registry-three-bands)
19. [Performance Characteristics](#performance-characteristics)
20. [Engineering Philosophy](#engineering-philosophy)
21. [What is not built](#what-is-not-built)
22. [Summary](#summary)

---

## What Is Luminary?

Luminary is a local-first personal knowledge and learning assistant. You feed it documents -- PDFs, books, research papers, code files, conversations, notes -- and it builds a queryable knowledge graph, generates spaced-repetition flashcards, surfaces learning gaps, and lets you have a conversation with your entire library. All of this runs on your machine. No data leaves your device unless you explicitly configure a cloud LLM key.

The system is not a thin wrapper around a chat API. It is a multi-store, multi-model application with an agentic routing pipeline, a hybrid retrieval engine fusing three search strategies, a full spaced-repetition scheduler, and an observability stack that traces every LLM call, retrieval query, and ingestion step. It is designed to be the kind of tool you would build if you took the question "How should I study this material?" seriously and answered it with software engineering.

---

## The Problem It Solves

Most AI-powered reading tools fall into one of two traps. The first is the "chat with your PDF" demo: a vector search over chunked text piped into a single LLM call. It works for a toy example but collapses when you ask a comparative question across two books, or when the answer requires understanding the relationship between entities mentioned in different sections.

The second trap is the cloud-only SaaS model. Your documents are uploaded to a third-party server, processed in someone else's infrastructure, and stored in someone else's database. For personal study materials, proprietary research, or anything you would rather keep private, this is a non-starter.

Luminary avoids both traps. It runs a multi-strategy retrieval pipeline locally, keeps all data in a directory on your own machine, and degrades gracefully when external services are unavailable. If Ollama is not running, you still get keyword search, entity browsing, and flashcard review. If no cloud API key is configured, the system uses local models for everything.

---

## Architecture Overview

The application is split into a Python backend (FastAPI, async-first) and a React frontend (TypeScript, Vite). They communicate over HTTP and Server-Sent Events (SSE) for streaming.

```
                    Frontend (React + TypeScript + Vite)
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

All structured metadata lives in SQLite: documents, sections, chunks, summaries, flashcards, notes, concepts, Q&A history, evaluation runs, and settings. SQLite provides ACID transactions, is embedded (no server), and stores everything in a single file -- `luminary.db`, under the data directory (`~/.luminary` for a source or script install, `~/Library/Application Support/sh.luminary.app` for the bundled macOS app).

Key tables include `documents` (metadata, ingestion status, SHA-256 file hash for dedup), `chunks` (text segments with section references and page numbers), `summaries` (cached per mode), `flashcards` (FSRS state, stability, difficulty, due date), and `concepts` (the hot learning state -- mastery, FSRS stability, origin, status, evidence refs).

The schema is Alembic-versioned and migrated to head on boot, so an upgrade never asks you to delete your library (I-23).

### SQLite FTS5 (Keyword Search)

Two FTS5 virtual tables -- `chunks_fts` and `notes_fts` -- provide BM25 keyword search. FTS5 is SQLite's built-in full-text search engine; it creates an inverted index over token-level terms and scores results by term frequency and inverse document frequency.

A practical lesson learned: UNINDEXED columns in FTS5 virtual tables are unreliable for `WHERE col = :val` queries when the table accumulates many rows. The workaround is to query the shadow content table directly (`notes_fts_content WHERE c1 = :nid`), where `c0`, `c1`, `c2` map to column order from `CREATE VIRTUAL TABLE`.

### LanceDB (Vector Search)

LanceDB stores dense embeddings for chunks, notes, images and concepts. Built on Apache Arrow, it is embedded (no server), supports fast cosine similarity search, and handles incremental upserts efficiently. Vectors are 384-dimensional, generated by the BAAI/bge-small-en-v1.5 model via SentenceTransformer.

Chunks and notes share one embedding space, so a question can reach both. Concept vectors are a *derived* centroid of a concept's evidence chunks in that same space -- used for similarity, linking and dedup, never as the primary retrieval path. Image vectors embed the vision model's description of a figure, which is what makes a diagram findable at all.

The table schema uses PyArrow native types (`list_(float32(), 384)`) for vector columns, with additional metadata columns (chunk_id, document_id, section_heading, page) for filtering and attribution.

### Kuzu (Knowledge Graph)

Kuzu is an embedded graph database supporting Cypher queries. It holds five node tables -- **Entity**, **Document**, **Note**, **Concept** and **DiagramNode** -- and 27 relationship types. A representative few:

- **MENTIONED_IN**: Entity is mentioned in Document (with count)
- **CO_OCCURS**: two entities appear together frequently (with weight and source document)
- **PROMOTED_FROM**: a Concept was promoted from a cluster of Entities
- **SAME_CONCEPT**: two concepts in different documents are the same idea under different names
- **PREREQUISITE_OF** / **CONCEPT_PREREQUISITE_OF**: ordering between things to learn
- **CALLS**, **IMPLEMENTS**, **DEPENDS_ON**: the call and dependency graph for code documents

**Entity and Concept are different layers, and the distinction matters.** An Entity is a lexical NER mention -- what the extractor saw. A Concept is the studyable atom: it carries mastery, it is what a study session routes over, and it is promoted from a cluster of entities rather than being one. Everything the learning engine measures hangs off Concept, not Entity.

The graph is traversed during retrieval (the "graph" leg of hybrid search), during chat routing (entity grounding for vague queries), and during gap detection.

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
chunk               Split into overlapping segments (content-type-aware sizes)
  |
  v
embed               Generate 384-dim embeddings (BAAI/bge-small-en-v1.5) -> LanceDB
  |
  v
keyword_index       Populate the chunks_fts BM25 index
  |
  v
entity_extract      Zero-shot NER (GLiNER) + disambiguation -> Kuzu
  |
  v
section_summarize   Per-section summaries
  |
  v
summarize           Document summary, assembled from the section summaries
  |
  v
enrichment_enqueue  Queue image_extract and concept_link; the document is
  |                 usable from here, the queue drains behind it
  v
complete            (error_finalize is the terminal node on any failed path)
```

Progress is tracked in real-time and surfaced in the UI: parsing = 10%, chunking = 40%, embedding = 70%, complete = 100%. The upload dialog stays open until ingestion finishes, so the user always knows what is happening.

Content-type classification uses a heuristic cascade: file extension for audio/video/code, structural patterns for conversations (speaker labels) and papers (abstract, methodology, references), word count and chapter patterns for books, and code-fence density for technical books. A fallback to LLM classification fires only when heuristics are inconclusive.

### Enrichment runs after ingestion, on a queue

A document becomes searchable once `embed` and `keyword_index` have run; enrichment is separate
work queued behind the pipeline and drained by `EnrichmentQueueWorker` — `image_extract`, then `image_analyze`,
plus `concept_link`. A document is usable before any of it finishes.

Image extraction pulls embedded rasters and, for pages that carry none, rasterizes clustered
vector drawings — without that fallback a LaTeX-authored paper yields zero figures, because
its figures are path operators rather than image XObjects. Each recovered figure then costs
one vision-model call to describe, and those descriptions are what image search retrieves.

**This is the most expensive thing the system does per document, and over-extraction is the
failure mode that matters.** A PDF generated from a reflowable source carries one fill
rectangle spanning the whole flow, which, if measured after being clipped to the page, looks
exactly like a page-sized figure. One 128-page book produced 81 "figures", 79 of them pages
of body text — hours of queued vision time spent paraphrasing prose the pipeline had already
chunked and indexed verbatim, and the paraphrases then made image search worse. The guard is
that a drawing primitive larger than its own page is a container, not ink, and the
measurement must happen before the clip (I-38). Re-extraction retires figures the current
extractor no longer produces, so an existing library is repaired by re-extracting rather than
re-uploading.

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
  +---> Vector Search (LanceDB)    cosine similarity on bge-small embeddings
  |
  +---> Keyword Search (FTS5)      BM25 term frequency scoring
  |
  +---> Graph Traversal (Kuzu)     entity co-occurrence + relationship paths
  |
  v
RRF Fusion:  score = SUM( 1 / (k + rank_i) )  for each strategy,  k=60
  |                                                   <-- L1: candidate generation
  v
Cross-encoder rerank over the top-RERANK_DEPTH (50) of the RRF pool
  |                                                   <-- L2: precision ranking
  v
Neighbour expansion:  +/- 1 chunk, scored below its parent
Diversification:  round-robin when one section dominates (skipped when reranking)
  |                                                   <-- L3: assembly
  v
Top-N scored chunks returned to caller
```

The funnel has three layers, and `docs/retrieval-funnel.md` is its live contract. **Graph is not
a separate ranked leg**: it contributes by expanding the candidate set, not by producing its own
ranking to fuse. Ahead of L1 there is also query spell-correction and corpus routing.

L2 is where most of the quality lives. Reranked HR@5 is bounded by HR@depth of the RRF pool, so
depth is the one knob that can actually move it -- and latency is linear in depth, about 5ms per
pair on CPU. That trade is why the default is 50 rather than "as much as possible".

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
classify_node        Keyword heuristics + LLM fallback. Routing is a conditional
  |                  edge, not a node -- the classifier's intent selects the arm
  |
  +--> summary_node       Fetch the cached document summary
  +--> search_node        Hybrid RRF retrieval + section augmentation
  +--> graph_node         Kuzu entity traversal + grounding retrieval
  +--> comparative_node   Dual retrieval (one per comparison subject)
  +--> notes_node         Hybrid FTS5 + semantic search over your notes
  +--> notes_gap_node     What the notes do not cover
  +--> socratic_node      Asks rather than answers
  +--> teach_back_node    You explain; it grades and probes
  |
  |                  socratic and teach_back are interactive modes: the
  |                  classifier may never select one on its own, because
  |                  choosing to be quizzed is the user's decision (I-26)
  v
synthesize_node      Context packer (dedup, section grouping, 3k-token budget)
  |                  + intent-specific system prompt
  |                  + LiteLLM streaming via SSE
  v
confidence_gate_node
  |
  +--[high | medium | already retried]--> END
  |
  +--[low + first attempt]--> augment_node / web_augment_node
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

Summarization is pre-computed during ingestion and cached in SQLite, so opening a summary costs no LLM call. That matters more than it sounds: on a CPU-only host a single generation is measured in tens of seconds to minutes, so "generate it when they open it" would make the feature unusable on exactly the machines this app targets.

**Three levels:**

1. **Section summaries**: each qualifying section (preview >= 200 characters) gets a 1-2 sentence summary, generated under a small semaphore (default 3). The bound is deliberate: concurrency comes from the runtime's serving width, and a wider app-side semaphore overlaps nothing -- it just moves the wait into Ollama's queue, where it counts against the caller's timeout (I-31). Stored in `SectionSummaryModel`.

2. **Document summaries**: Three modes, each generated from section summaries (not raw chunks):
   - `one_sentence`: 30 words or fewer, single-sentence gist
   - `executive`: 3-5 overarching themes or arguments
   - `detailed`: Per-section summaries preserving heading structure

3. **Library overview**: On-demand synthesis across all documents, using document-level executive summaries as input.

**The fast-path optimization**: Traditional map-reduce summarization requires (a) chunking the entire document, (b) summarizing each chunk batch (the "map" step), (c) concatenating batch summaries, and (d) a final reduction. For a 100-section book, this means dozens of sequential LLM calls and can take 15+ minutes.

The fast path short-circuits this: if section summaries already exist (they do -- they were generated during ingestion), use them directly as input to the mode-specific LLM call. One call, not dozens. On a long book that is the difference between a summary you can wait for and one you abandon.

**Cache-first strategy**: `GET /summarize/{id}/cached` returns all stored summaries instantly (no LLM). `POST /summarize/{id}` checks the cache first; on cache hit, it returns the cached content as a single SSE event. On cache miss, it generates, stores, and streams. The map-reduce intermediate is also cached (pseudo-mode `_map_reduce`), so even an on-demand request for a new mode skips the expensive map step.

---

## The Learning Engine

Luminary is not just a reading tool. It is a learning tool. The pieces below work together to
help the user internalize the material, and they route over **concepts** -- the studyable atom
-- rather than over documents.

### FSRS Spaced Repetition

Flashcards are scheduled with the `fsrs` library, v6's `Scheduler` (not SM-2, which is what
Anki's classic algorithm uses). Each card tracks:

- **Stability**: Resistance to forgetting (higher = longer retention intervals)
- **Difficulty**: Predicted future forgetting curve (affects interval growth rate)
- **State**: learning, review, relearning, or new
- **Due date**: Earliest review date (cards not yet due are hidden)

After each review (user rates: Again / Hard / Good / Easy), the FSRS scheduler updates stability and difficulty, computes the next due date, and persists the state. The system also tracks reps (total reviews) and lapses (times the user rated "Again"), which surface in the study progress dashboard.

Stability is also read *upward*: a concept's mastery is derived from the FSRS state of the cards
that evidence it, which is why "what am I about to forget" is answerable without asking a model.

### Study orchestration

A session is assembled rather than improvised. `POST /study/assemble` builds one from what is due,
what is fading and what a document's concepts demand; `GET /study/session-plan` returns the plan
before you commit to it; `POST /study/sessions/start` and `.../end` bracket the work and write the
record the progress surfaces read. `docs/two-lane-model.md` and `docs/study-launcher.md` are the
live contracts.

### Cards that quote their source

A generated flashcard carries the passage it came from (`source_chunk_ids`) and a per-card
grounding verdict, shown at review time and auditable across a deck. A card whose evidence cannot
be found in the document it claims is rejected rather than shown. The prompt's own worked example
is named in code and refused explicitly, so the model cannot pass the grounding check by pasting
back text the system supplied (invariants I-34 and I-35).

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

## The Frontend: A 72px Nav Rail, Seven Learner Surfaces, Three Dev Surfaces

The frontend is a single-page React 19 application. A fixed 72px violet-gradient sidebar on the left holds seven learner-facing tabs (top of rail) plus three dev surfaces (bottom of rail). The rail is generated from `surface-manifest.json`, not hardcoded, and surfaces marked `full` (Map and all three dev tabs) are absent from a `public` build. A 450px slide-over chat panel docks on the right, callable from anywhere. `Cmd+K` opens a global search dialog over whichever tab is active.

The post-refactor labels (`Ask` instead of `Chat`, `Map` instead of `Viz`) are cosmetic only — the underlying routes (`/chat`, `/viz`) are preserved so deep links and the cross-tab `luminary:navigate` event bus keep working.

### Luminary (`/`, icon: Luminary lantern glyph)
The hub, and the landing surface. One 780px reading column answering the single decision it exists for — carry on reading, or start the review — then today's focus, the continue lane (documents, notes and an open study session), the fading/refresher lane, tag cloud, active collections and a week summary. All of it comes from one `GET /home/overview` fetch. Stored titles render through `humanizeTitle`, because in one real library two thirds of titles were the filename the document arrived as.

### Library (`/library`, icon: BookOpen)
The document grid. Cards carry a 1px top-edge gradient accent band per content-type (book, paper, code, audio, epub, kindle, tech-book, tech-article, conversation, youtube), hover-lift on `-translate-y-0.5`, content-type badge, eyebrow metadata row, and an action menu (read, chat about, study, view in graph, delete). A `TodayHero` strip at the top of the page surfaces the highest-leverage action: if cards are due, a full-violet "N cards due · Start review" CTA wins primary placement; otherwise the existing low-contrast "Continue reading" strip falls back in. Clicking a card opens the `DocumentReader` in place; PDF/EPUB/YouTube each render in their own viewer with shared chrome.

### Notes (`/notes`, icon: StickyNote)
Markdown notes with collections (sidebar tree), tags (sidebar list, auto-suggested via `NoteTaggerService`), source-document linking, link autocomplete between notes, and embeds (Mermaid diagrams, Excalidraw sketches). The list view supports filter-by-collection, filter-by-tag, filter-by-source-doc, and FTS5 + vector hybrid search. Notes opens its editor in a side sheet (`NoteReaderSheet`).

### Study (`/study`, icon: BarChart2)
Flashcard review with FSRS scheduling (Again / Hard / Good / Easy), teach-back sessions (free-text explanation graded against the source for accuracy, completeness, clarity), and a collection-scoped study dashboard that surfaces struggling cards, deck health, and Bloom-taxonomy distribution.

### Ask (`/chat`, icon: MessageSquare)
Conversational Q&A backed by the agentic chat graph. Scope selector chooses single document, all documents, or selected documents. Responses stream in real-time via SSE with inline citations (section heading, page number, clickable excerpt). Sessions are persisted; the left rail lists past chats grouped by date. The same Chat component also renders in a 450px right slide-over panel that's callable from any tab.

### Map (`/viz`, icon: Network)
WebGL knowledge graph using Sigma.js v3 and Graphology. Entity nodes are colored by type, edges show relationship labels (co-occurrence, prerequisite, same-concept, mentioned-in). Sidebar filters by entity type, retention strength, and document scope. View modes include the default entity graph, a tag graph, and a code call-graph for ingested source files. Handles 10,000+ nodes smoothly via GPU-accelerated rendering.

### Progress (`/progress`, icon: Luminary lantern glyph)
The learner's progress dashboard: streak + XP widget, FSRS due-count, knowledge gap scanner (LLM-graded gap detection against notes), study activity (last 30 days), notes-over-time chart, and the study habits section. The nav icon is a custom `LuminaryGlyph` SVG (lantern silhouette) — the only custom icon on the rail; all other nav icons are Lucide stroke-style.

### Dev rail (bottom of sidebar)

- **Quality (`/quality`, icon: ClipboardCheck)** — the retrieval and generation eval dashboard. Demoted from the learner rail because it is an engineering surface, not a learner one.
- **Monitoring (`/monitoring`, icon: Activity)** — Phoenix traces and run history.
- **Admin (`/admin`, icon: Wrench)** — dev tools: ingestion queue, model usage, recent OpenTelemetry traces, mastery heatmap, weak-spots panel.

**Architectural patterns:**
- All tabs lazily loaded (React.lazy + Suspense) to keep the initial bundle small
- Nav-link hover triggers TanStack Query prefetch for the destination tab's primary query
- All API state is managed through TanStack Query (staleTime 60s, no refetch on window focus)
- Global UI state (active document, chat scope, library view, etc.) lives in Zustand stores (`store.ts` for the main app, `vizStore.ts` for the graph)
- API responses are typed via openapi-generated `frontend/src/types/api.ts` (regenerated from the FastAPI schema); the `apiClient` helpers in `lib/apiClient.ts` wrap fetch with typed payloads
- Design tokens live in `frontend/src/index.css`: shadcn token base, expanded `--type-*` content-type accents, motion easings, shadow tiers, type scale, and the `.lum-*` semantic role classes (`lum-h1` through `lum-mono`, `lum-eyebrow`)
- The 72px sidebar gradient (`bg-gradient-to-b from-sidebar via-sidebar to-primary/5`) is the most decorative element in the app; everything else stays calm

---

## Observability and Evaluation

### Arize Phoenix (Tracing)

Every LLM call, retrieval query, and ingestion step is traced via OpenTelemetry. Phoenix runs as an in-process server on port 6006, storing traces persistently under the data directory (`phoenix/`). Custom span types include:

- **Chain spans** for LangGraph nodes and service orchestration
- **Retriever spans** for vector/keyword/graph search with chunk count and latency
- **LLM spans** (auto-instrumented via LiteLLMInstrumentor) with messages, token counts, and model name

### Retrieval and generation evaluation

Quality is scored against golden datasets (`evals/golden/*.jsonl`). Each entry carries a
question and a `context_hint` substring that must appear in the retrieved context for a
"hit". Faithfulness uses a dedicated NLI model (Vectara HHEM-2.1-Open), not an LLM judge,
so it is deterministic and needs no API key.

| Metric | Floor | Asserted |
|---|---|---|
| HR@5 | 0.50 | yes |
| MRR | 0.35 | yes |
| Faithfulness (NLI) | 0.30 | when a run generated answers |
| Answer rate | 0.75 | when generation was requested |
| Citation coverage | 0.60 | when generation was requested |
| Citation support | 0.45 | when `--check-citations` |
| nDCG@10 | 0.40 | **no — reported only** |

Per-dataset overrides raise the bar where a corpus measures higher: `paper` 0.80 / 0.60,
`play` 0.70 / 0.50, `notes` 0.60 / 0.45. The live values are `THRESHOLDS` and
`DATASET_THRESHOLDS` in `evals/run_eval.py`; that file, not this one, is the source of truth.

**These floors are collapse detectors, not quality bars.** Clearing them says a leg of the
funnel is alive, not that a change was good. Two consequences that are easy to get wrong:

- **Faithfulness 0.30 is not "30% correct".** HHEM scores grounding in the retrieved
  context, not truth — a correct answer written from parametric knowledge scores low by
  design. Measured on `d2l` (12 answers): dataset mean 0.46–0.48, nothing above 0.66. The
  inherited RAGAS bar of 0.65 would have failed 11 of 12. The distribution is unimodal, so
  there is no gap to place a quality bar in without labelled answers.
- **nDCG@10 is not a gate.** Most goldens carry single-passage relevance, where nDCG
  degrades to a log-discounted single-hit metric. It is promoted only once graded goldens
  exist.

Generation metrics carry real run-to-run variance on a frozen build: `book`'s citation
support ranged 0.5893–0.7065 across four identical runs. **A single run cannot resolve a
generation change smaller than ~0.10 on `book` or ~0.05 on `paper`** — compare distributions
over repeated runs, never two points. Retrieval metrics are exempt: they are
bit-reproducible on a fixed corpus.

A metric that was requested and could not be computed **fails** the run; it is never
defaulted to a neutral value. Retrieval baselines on the shipped funnel (rerank on, 50
documents / 75,537 chunks, 2026-08-26) are recorded next to the thresholds — compare a
change against those, never against the floor.

The corpus spans 27 golden files: retrieval sets for `book` (three books, 40 rows each),
`paper`, `legal`, `play`, `study` (PDF), `d2l`, `notes`, `conversation` and `code`, plus
labelled sets for intents, flashcards and summaries.

---

## Deployment Model

Luminary is a **local-first desktop application**:

```
User's machine
  |
  +-- Ollama (local LLM server, default: qwen3.5:4b)
  |
  +-- Luminary Backend (FastAPI, uvicorn, port 7820)
  |     |
  |     +-- the data directory
  |           +-- luminary.db       (SQLite: all structured data)
  |           +-- lancedb/          (LanceDB: chunk, note, image, concept vectors)
  |           +-- graph.kuzu        (Kuzu: knowledge graph)
  |           +-- raw/              (uploaded file copies)
  |           +-- images/           (figures extracted from documents)
  |           +-- audio/            (transcoded media)
  |           +-- models/           (bge-small, GLiNER, reranker cache)
  |           +-- phoenix/          (trace storage)
  |
  +-- Luminary Frontend (Vite on 5173 in dev; served by FastAPI in a build)
```

**Prerequisites:**
- Python 3.13 with uv (package manager)
- Node 20+
- Ollama with at least one model pulled. `make install` pulls what your RAM
  band needs; by hand, `ollama pull qwen3.5:4b` covers every role.

**Startup:**
```bash
ollama serve        # Terminal 1
make dev            # Terminal 2 (starts both backend and frontend)
```

The data directory is `~/.luminary` for a source or script install, and
`~/Library/Application Support/sh.luminary.app` for the bundled macOS app. It sits outside
whatever an upgrade replaces, which is why updating never touches your library.

**All data stays local.** The backend binds to `127.0.0.1:7820` (not `0.0.0.0`). CORS allows only
localhost origins. There is no authentication -- this is a single-user local app, and that
assumption is baked into the persistence model rather than being a feature yet to be added.

**API keys go to the OS keychain where there is one.** In a container there isn't, so the key is
written to SQLite behind a `__plain__:` prefix and the README says so plainly -- a test fails if
it stops saying so. Pass the key as an environment variable under Docker instead.

**Cloud LLM is opt-in.** If the user configures an OpenAI, Anthropic, or Google API key, LiteLLM routes requests to the cloud provider. Otherwise, all LLM calls go to Ollama. The system degrades gracefully when Ollama is offline: search, entity browsing, and flashcard review still work; features requiring LLM (summarization, chat, flashcard generation) return HTTP 503 with an actionable message ("Ollama is unreachable. Start it with: `ollama serve`").

**Desktop packaging.** Luminary ships as a signed, notarized macOS `.dmg`, built with Tauri:
the frontend bundle in a native shell, with the Python backend and a bundled Ollama as
sidecars. `docs/desktop-bundle.md` is the contract. The same codebase also runs from source on
Linux and Windows, and under Docker -- where inference is best pointed at the host or a hosted
model, since no GPU passes through.

---

## Model Selection: One Registry, Three Bands

Which model answers a question is not a constant, and it is not read from config
at the call site. `app/model_registry.py` is the only module that reads a model
name out of configuration; everything else asks the router for a **role** --
`chat`, `generation`, `background`, or `vision` -- and gets back whatever the
current configuration resolves to. A test fails the build if a service starts
reading a model id directly, because a model chosen in Settings has to reach
every call site or none.

### The registry knows what a model costs

Each entry carries a measured footprint rather than an estimate: resident bytes
from Ollama's own `/api/ps` after a real generation at the deployed context
window, which is weights plus one KV cache. The estimates these replaced were low
by up to 44%, and the number decides whether a model is offered on a machine at
all.

`min_ram_gb` is the one derived value, and it is policy: twice the resident size,
the model taking half the machine while the other half carries the OS, the
backend's 4.7 GB ingest peak, the embedder and the entity model.

Capability is measured too, not declared. Two entries were recorded as text-only
while both could read images, which left the vision role resolving to a 6.8 GB
model an 8 GB laptop could not hold -- and no feasible assignment of models to
roles on that machine at all. A test now checks every entry's declared
capabilities against what the runtime reports.

### Three bands, decided by RAM

| RAM | Profile | Text roles | Vision | Resident |
|-----|---------|-----------|--------|----------|
| under 16 GB | `low` | `qwen3.5:4b` | the same model | 3.2 GB |
| 16-24 GB | `standard` | `qwen3.5:4b` | the same model | 3.2 GB |
| over 24 GB | `performance` | `qwen2.5:14b-instruct` | `qwen3.5:4b` | 12.9 GB |

The band picks the role map, and a second model loads only when both fit
*together*. That is the per-model rule applied to the resident set: two models
break the assumption the per-model rule rests on, because "the other half carries
everything else" is a budget that does not double when a second model loads. A
16 GB laptop cannot hold a 3.2 GB text model beside a 6.8 GB reader -- 10 GB is
63% of RAM before the ingest peak and 92% after -- so what the larger band buys
that machine is serving width, not a second model.

Text and vision are chosen as a pair, because the strongest text model is not
multimodal: picking it first can leave the vision role with nothing the host can
also hold. The choice is an enumeration over a handful of candidates with a
written-down preference order, not an optimisation -- the whole feasible space
across all three bands is small enough to read.

### One context window per loaded model

Ollama keys a loaded runner on `num_ctx`, so a call asking for a different window
unloads llama-server and reloads it. Three call-site-specific windows once made a
single chat turn reload the model twice. The window is therefore a property of
the model, read from its registry profile, and no call site chooses one.

Shrinking it was measured and rejected: on `qwen3.5:4b`, 8192 costs 3.21 GB,
6144 costs 3.15 GB and 4096 costs 3.00 GB. The 60 MB saved by 6144 is 0.7% of an
8 GB machine and halves the flashcard path's headroom; the only saving worth
having is at 4096, which cannot hold the largest prompt the app builds and
truncates rather than erroring.

### Configuration, and what happens when it does not fit

Three layers, strongest first: what you pick in the app's Settings (stored in the
database), then `backend/.env`, then the RAM-sized registry default. Only the
default is host-aware -- an explicit choice is honoured even when it does not fit,
because a backend that refuses to start over a model choice is worse than one
that says the choice is expensive.

What it does instead is warn: at startup in the log, at `GET /settings/models`,
and in `make models`. The warning is not cosmetic. A configuration that exceeds
the host swaps under load, and its first symptom is a stall during ingestion
rather than an error.

---

## Performance Characteristics

**Three latency and memory assertions exist, and none of them runs in `make ci`.**
`backend/tests/test_performance.py` is `@pytest.mark.slow`, and `slow` is excluded by
default. Run them deliberately:

```bash
cd backend && uv run pytest tests/test_performance.py -m slow
```

| What is asserted | Bound | Caveat |
|---|---|---|
| Hybrid search latency | p50 < 500ms, p95 < 2000ms over 20 queries | in-process stores, no model call |
| 10 documents reach `complete` | < 120s | **mocked embedder** — measures the pipeline, not ML |
| RSS growth over 10 ingests | < 500MB | growth only, not total footprint |

Everything else below is a measurement, not a gate.

**Local generation is the cost, and it is measured in minutes on CPU.** Nothing about the
retrieval stack is slow; the model is. On an Intel i7-8850H (CPU-only, Docker, host Ollama,
`qwen3.5:4b`): a question through `/api/qa` took 121s, five flashcards 118s, and enriching a
128-page book 143s. The same work on Apple Silicon is a small fraction of that. A model load
alone on that host measured 9.6s–155.5s and is billed to whichever call provokes it (I-37),
so a single slow call is not evidence about the component that reported it.

**In-process store latencies** (no network hop, measured on Apple Silicon): LanceDB vector
search sub-5ms, FTS5 BM25 sub-10ms, Kuzu traversal sub-20ms.

**Key optimizations**

- Embedding runs on ONNX Runtime for CPU inference (batch 128, normalize in-place).
- GLiNER uses `batch_predict_entities()` for single-pass NER.
- Section summaries run under a semaphore sized *at* the Ollama slot count — enrichment cost
  is call count, never concurrency (I-31). More parallelism against one Ollama slot buys
  nothing and starves interactive questions.
- Context packing compares only the first 300 characters, so its O(n^2) step stays small.

**Memory.** Resident footprint while ingesting is ~7.6GB: Ollama serving `qwen3.5:4b` 4.2,
PyTorch + embedder 0.8, reranker 0.2, GLiNER 1.3, plus ~1.1 peak during ingestion. Answering
questions afterwards sits near 6.5GB. **Give Luminary 12GB; 8GB is the floor where it runs
but swaps under load.** These figures are read off a running instance, not estimated, and are
the same ones the README quotes.

**The vision model is a second resident model, and it is not in that 7.6GB.** Ollama's
`OLLAMA_MAX_LOADED_MODELS` defaults to 3, so a chat runner and a vision runner co-reside for
the length of `OLLAMA_KEEP_ALIVE`. The script installers cap it; the DMG path does not yet
(`docs/roadmap.md`). Enriching a document with figures on an 8GB machine is therefore the
case most likely to swap. A model's context window is a property of the model, not of the
caller (I-27) — two callers of one loaded model share a single window, and no call site can
ask for a larger one.

---

## Engineering Philosophy

The practices here were not adopted from a framework. Each one is the residue of something that
went wrong, which is why they read as specific rather than aspirational.

**The repository is the system of record.** Architecture, patterns and invariants live as
versioned Markdown in `docs/`, and every file there describes something that **exists**.
`docs/roadmap.md` is the single exception and the only place status lives -- an implementation
plan is deleted once its work ships, because a shipped spec left lying in the tree is
indistinguishable from a live contract to anyone reading it for the first time.

**Invariants are mechanical, and each names its incident.** `docs/invariants.md` carries 38 of
them, grouped by Async/Concurrency, FTS5/SQLite, Imports, LLM/SSE, Vector Dimensions, Frontend,
Quality Gates, Packages, and Privacy. Each is written as incident -> rule -> mechanism -> the
test that guards it, because a rule without a mechanism is a preference. `layer_linter.py`
fails the build on a reverse import and its `KNOWN_VIOLATIONS` set may only shrink.

**Nothing the system supplies may satisfy a check on the system's output.** A flashcard prompt's
worked example once contained a plausible `source_excerpt`, and the model pasted that exact
string back as its evidence for two unrelated documents. It was rejected by luck, not by
mechanism. That example text is now named in code and refused explicitly. When a check reads
something a model produced, the question to ask is where else that value could have come from --
and if the answer includes "from us", the check is decorative.

**A check that cannot fail is not a check.** A judge asked whether a card was "atomic", with the
term undefined, returned true for every card in a sample that was two thirds multi-point answers
-- a perfect score that certified nothing. Fire every gate on purpose once, and see it fail,
before trusting it.

**Floors detect collapse; they do not measure quality.** The eval thresholds fire when a leg of
the pipeline dies. Clearing them says the funnel is alive, not that a change was good. A metric
that was requested and could not be computed **fails** the run rather than being skipped -- it is
never defaulted to a neutral value.

**Never buy a number by spending the content.** A `max_tokens` cap once cut worst-case latency
from 173s to 52s by truncating the stored summary mid-word, dropping half the document. The
latency table looked like a win. Bound the work, never the output.

**Tests use real artifacts at real scale.** Integration tests ingest full, untruncated
public-domain books with real ML models. Only the LLM is mocked, so CI does not need Ollama.

**Pure functions for core domain logic.** RRF fusion, scoring, diversification, response parsing
and text transformations take inputs and return outputs -- no I/O, no network, same answer every
time. They are testable with a bare `assert` and no fixtures.

---

## What is not built

Status lives in one place: [`docs/roadmap.md`](docs/roadmap.md) — what is built, what is
open (each item carrying `file:line` evidence), and what was deliberately abandoned. It is
the only file in the repo that describes work that does not exist, and an implementation
plan is deleted there once its work ships.

Two limits are structural rather than scheduled, and worth stating here because the
architecture assumes them:

- **Single user, no authentication.** Every store is a local file opened by one process.
  Collaboration, per-user isolation and shared-entity conflict resolution are not
  deferred features; they would change the persistence model.
- **One Ollama context window, shared.** Model residency is a measured property of the
  host, not a constant (I-37), and the context window is global to a loaded model (I-27).
  Anything that assumes per-request model isolation does not hold here.

---

## Summary

Two constraints produce every design decision above: all data stays on the user's machine,
and the system has to be useful for *learning*, not only for querying. Polyglot persistence,
hybrid retrieval, agentic routing, hierarchical summarization and spaced repetition each
follow from one or both.

The cost of that is complexity a single-store RAG demo does not carry, and the thing that
keeps it navigable is mechanical enforcement rather than discipline: the layer linter, the
38 invariants, the surface manifest and the eval floors are all gates a change has to pass
rather than conventions it can drift from.
