---
description: Luminary hard invariants. Each was learned from a real incident or design decision; each names the gate that enforces it.
---

# Luminary Invariants

These are non-negotiable. Each one exists because its violation caused a real bug or regression.

## Async / Concurrency

**I-1. Never share AsyncSession across `asyncio.gather` tasks.**
Each concurrent task needs its own session or a `Semaphore(1)` serialiser. SQLAlchemy AsyncSession is not safe for concurrent use.

**I-2. Wrap all synchronous LanceDB *and Kuzu* calls with `asyncio.to_thread`.**
Both are synchronous. Calling either directly in an async function blocks the event loop -- and because the server runs a single worker, it stalls *every* concurrent request, not just the slow one. Measured: a 2ms `/tags/graph` took 8.5s sitting behind one all-library `/graph` traversal, which is why the Map's Tags view appeared to hang. Kuzu is safe to call from a worker thread: `ThreadSafeKuzuConnection` already serializes every `execute()` under an RLock. The same rule covers any long CPU call with no `await` inside it. `parse_node` ran `DocumentParser.parse` inline and froze the loop for a measured 44.9s on a 23MB PDF (3.96s once moved to `asyncio.to_thread`). In `public` mode that is worse than a slow API: the backend also serves the SPA, so its lazy route chunks never arrive and the UI cannot navigate at all -- clicks appear dead while hover still works, because only the server side is stalled. `chunk`, `entity_extract` and `transcribe` are still inline.

**I-3. Always guard Kuzu `get_next()` with `has_next()`.**
`get_next()` raises if no rows exist. Every Kuzu result iteration must call `has_next()` first.

## FTS5 / SQLite

**I-4. Do not use `WHERE unindexed_col = :val` on FTS5 virtual tables.**
UNINDEXED columns are unreliable for equality filtering when the table is large. Query the shadow content table directly: `notes_fts_content WHERE c1 = :nid` (columns c0, c1, c2 match CREATE VIRTUAL TABLE order). Deletion: `DELETE FROM notes_fts WHERE rowid = :rowid` (rowid-based delete always works).

## Imports

**I-5. Never import at module level inside a service if it creates a circular dependency.**
Use lazy imports inside the method body: `from app.runtime.X import fn  # noqa: PLC0415`. Patch target is then `app.runtime.X.fn`, not the call-site import.

**I-6. Import `get_settings()` at module level in services.**
Never suppress `get_settings()` exceptions with bare `except`. Never lazy-import settings -- it makes the patch target unpredictable in tests.

## LLM / SSE

**I-7. Persist rows before LLM calls in SSE generators; add explicit rollback on error.**
Implicit rollback on session close is insufficient after a generator exception. Add explicit `await session.rollback()` in the error handler.

**I-8. The `done` SSE event payload contains the clean `answer` field.**
The frontend must replace `msg.text` with `payload.answer` on the done event. Streamed tokens include citation JSON fragments -- never leave raw accumulated tokens as the final displayed text.

## Vector Dimensions

**I-9. Note and chunk vectors are 384-dimensional (bge-small-en-v1.5 output).**
The LanceDB schema must declare `pa.list_(pa.float32(), 384)`. Notes and chunks share one embedder and one vector space, so a note vector is directly comparable to a chunk vector. Any table declaring a different dimension is a bug.

## Frontend

**I-10. Every frontend feature must have loading, error, and empty states.**
No blank panels. Loading = skeleton (not spinner blocking the page). Error = inline message per section. Empty = explicit "No X yet" message.

**I-11. Cross-tab navigation uses the `luminary:navigate` DOM event and Zustand store.**
Never use URL hacks or React Router state for cross-tab navigation. Dispatch `new CustomEvent('luminary:navigate', { detail: { tab, filter } })` and handle it in App.tsx.

**I-12. Never use MarkdownRenderer inline in list/table cells.**
Block-level elements (h1, ul) inside a `<td>` break layout. Use `stripMarkdown()` from `src/lib/utils.ts` for single-line text previews.

## Quality Gates

**I-13. `make ci` is the gate, and it runs in order: ruff -> layer_linter -> boundary_checker -> pytest -> frontend build -> tsc.**
The order is load-bearing, not cosmetic: a lint error masks the test error underneath it, and a layer violation is a design fault that makes the test result meaningless. Run the cheap check first and fix what it says before moving on; running `pytest` against code `ruff` has already rejected wastes the slow step. Claiming a change is done means `make ci` exited 0 on your machine -- naming the individual commands you ran instead is not the same claim, because `make ci` also runs `check_manifest_schema.py`, `check_manifest_coverage.py` and `check_public_import.sh`, which are the ones people forget. Local green is necessary, not sufficient: GLiNER memory pressure has produced GitHub-only failures that no local run reproduces.

**I-14. `make ci` passing does not mean the app works. `make smoke` is the HTTP contract check.**
`make ci` runs `pytest` against the app in-process; it never starts a server, so it cannot catch a route registered in the wrong order, a router the manifest does not cover, or a response shape the UI reads differently than the test does. `scripts/smoke/all.sh` drives ~230 numbered `S###.sh` scripts against a live backend on :7820 and is the only thing that verifies the wire contract the frontend depends on. A change that adds or alters an endpoint is not finished until it has a smoke script and `make smoke` exits 0. There is no reviewer gate and no `passes=true` flag -- an earlier version of this invariant named both, and neither ever existed in the repo, so any claim of having satisfied them was unfalsifiable. If you want a review, `/code-review` is the mechanism.

## Packages

**I-15. Use `uv` only -- never `pip` or `poetry`.**
The lockfile is `uv.lock`. Adding packages: `uv add <package>`. Never run `pip install` directly.

## Privacy & Local-First

**I-16. Prioritize local LLM (Ollama) and local search (none/duckduckgo) by default.**
Never introduce a new external API dependency (e.g., Tavily, OpenAI) without providing a local-first or privacy-preserving alternative.

**I-17. Never log or transmit user content (notes, documents) to external telemetry.**
Arize Phoenix and Langfuse must be configured for local use only. Telemetry is for performance metrics and trace structure, not for content mirroring.

**I-18. Explicitly disable telemetry in third-party libraries (e.g., LiteLLM, LangChain).**
Check and disable any "phone home" features in libraries that handle user prompts.

## Concepts & Knowledge Layer

**I-19. Mastery is a stored scalar on the concept row -- never recomputed by text match, never on documents or collections.**
The legacy `chunk.text ILIKE '%name%'` mastery computation is removed. Mastery is written by the assessment pipeline (Study Events) to `concepts.mastery`. Collection/goal numbers are computed rollups, never stored as truth. See `docs/concepts.md`.

**I-20. The concept vector is derived and never a retrieval primary.**
A concept's LanceDB vector (`concept_vectors_v1`) is the 384-dim centroid of its evidence-chunk embeddings, in **chunk space** (bge-small-en-v1.5; chunks, notes, and concepts are all 384-dim in one shared space). Recomputed when evidence changes. Use it only for concept-to-concept and material-to-concept similarity (linking, dedup, candidate seeding, scope resolution). Chunk vectors + FTS5 + graph (RRF) remain the RAG backbone.

**I-21. OKF is a projection, never a transport and never a source of truth.**
LiteLLM carries bytes; OKF carries portable knowledge -- never couple them. OKF files are regenerated from SQLite + Kuzu. A user edit to an OKF file re-enters the system only as an `override` (re-applied after re-parse), exactly like a graph rename/merge. See `docs/okf.md`.

**I-22. A rejected or edited graph element must not reappear after re-parse.**
Re-parse produces fresh proposals, then `applyOverrides()` re-applies every user decision on top. Rejected concepts/edges and dismissed gaps stay gone (hidden, not deleted). Overrides survive re-parsing -- they are the user's permanent voice over Lumen's guesses.

**I-23. Schema changes are Alembic revisions. The `ALTER TABLE` list in `db_init.py` is frozen.**
`models.py` is the source of truth; `make db-revision m="..."` generates the migration and the server applies it on boot. `db_init.create_all_tables()` is a one-time bridge that lifts pre-Alembic databases to the baseline -- never add to it. Generate revisions ONLY via `make db-revision` (it diffs against a throwaway database): pointed at a long-lived one, autogenerate emits `drop_table()` for real user tables. `tests/test_schema_drift.py` fails CI when models and migrations disagree.

**I-24. Never add code that clears a Kuzu lock or kills a process holding one.**
Kuzu takes an exclusive OS-level file lock that the kernel releases the instant the holder dies (verified against SIGKILL; no lock artifacts on disk). A stale lock therefore cannot exist, so any "release the stale lock" logic can only ever kill a LIVE process mid-write -- which is how a graph database gets corrupted. A held lock means a real second process (another server, or `make concepts`): surface it and let the user stop it. A hand-rolled lockfile is strictly worse than Kuzu's own, because ours *can* go stale.

**I-25. Scope decides WHERE to look, never WHAT was asked.**
`scope='all'|'single'` must not influence intent classification. Telling the classifier to prefer `summary` when scope is the whole library made every bare topic ("Apache Iceberg") a summary request under All-documents while the identical query returned `factual` under a single document. Any node that cannot serve its intent falls through to retrieval (`return {"intent": "factual"}`, which `_route_after_strategy` sends to `search_node`) rather than answering with a placeholder -- a question always gets a real answer.

**I-26. The LLM intent classifier picks a retrieval strategy, never an interactive mode.**
`teach_back`, `socratic`, `notes` and `notes_gap` change what the chat *does* with the message rather than where it looks: teach_back grades it as the learner's own explanation, socratic answers with a question, the notes modes read personal notes instead of the document. A mode is only ever right when the user's phrasing asks for it, and `classify_intent_heuristic` matches that phrasing at 0.95 and returns without calling the LLM. The LLM is therefore only consulted about messages that are *not* mode requests, so any mode it names is a misfire -- an analysis-shaped question came back `teach_back` and was answered with an empty correct/misconceptions/gaps card. `_llm_classify_fallback` chooses from `_LLM_SELECTABLE_INTENTS` only; anything else becomes `factual` (per I-25, a question always gets a real answer). Adding a mode means adding keywords, not loosening the whitelist.

**I-27. One Ollama context window for every local call.**
Ollama keys a loaded runner on `num_ctx`, so a call requesting a different window unloads llama-server and loads it again (~1s idle, far worse under GPU contention). `num_ctx` is a property of the model, not of the call site. Three per-site windows -- 2048 default, 4096 QA, 8192 generation -- made a single chat turn reload the model twice and a question asked during ingestion reload it repeatedly. `OLLAMA_NUM_CTX` is the only window: size it for the largest single prompt and never override it per call. `tests/test_single_local_context_window.py` fails CI on a second knob or a divergent call site.

**I-28. A generation prompt states the shape of what it wants, never the name of a taxonomy.**
Suggested questions were generated by naming the Bloom level in the prompt ("6 questions at Bloom taxonomy level 5 (Evaluate)"). A small local model does not infer a pedagogy from its label; it pattern-matches the word to the register it has seen it in, and returns exam papers -- "Evaluate how X's reliance on Y can be advantageous" -- which no reader would type and which trips I-26 by reading as a learner's explanation. The level selects plain-language guidance in `_LEVEL_GUIDANCE`; the taxonomy word never reaches the model, and the wire key is `depth`, not `bloom_level`. The same rule covers few-shot context: prior questions reach the prompt as bare topic words (`_history_topics`), because injecting them verbatim under "avoid these" hands the model dozens of exemplars whose register it copies. `tests/test_suggestions.py` fails if any taxonomy term reappears in a rendered prompt.

**I-29. The reader never reconstructs prose from retrieval chunks.**
Chunks are sized for the embedder, not the eye: they cut mid-sentence, they overlap, and 90% of them contain no paragraph break at all (261 of 2,599 measured on `frankenstein` + `the_odyssey`). Re-joining them with `\n\n` fabricates a false paragraph break every few hundred characters and duplicates text at every overlap seam. Reading text comes from `sections.body`, which is uncapped; `sections.preview` is a 10,000-char snippet for section lists and flashcard context and is truncated mid-sentence on any longer section, so it is not reading text either. `GET /sections/{id}/content` returns `content_source` (`body` | `preview` | `chunks`) so a degraded tier is visible rather than silent -- `chunks` serves only documents ingested before the column existed, and those must be re-uploaded. `tests/test_section_content_reader.py` fails CI if the reader prefers a lossy tier over `body`. See `docs/universal-reader.md`.

**I-30. A heading is a label the source authored. Nothing invents one.**
The reader draws a section heading only when the stored `heading` is non-empty and reads like a label (`hasAuthoredHeading`); an unlabelled section is rendered without one. Three sites used to fabricate headings and each produced the same artifact -- an oversized `<h2>` printing text that then repeated immediately below it, or an empty section under a swallowed line. `universal_parser._segment` stored a whole matched line as the heading, which for a transcript IS the utterance (`_is_marker` now sends prose to the body); `_segment_chat_grouped` synthesised "Transcript Part 2: Carol", naming whichever speaker opened the group; and `chunk.py` substituted `f"Section {n}"` for every empty heading. An empty heading is the signal that the source gave none, so nothing downstream may fill it -- `sectionTitle()` still derives a label, but only for the contents panel, which needs an entry to navigate with. Empty-bodied sections are dropped rather than filled with placeholder text: a document's contents page matches the same signature as its chapter openings, so half the sections found in `the_odyssey.txt` (23 of 49) were empty twins that used to read "(Empty Section)". `tests/test_universal_parser.py` and `sectionTitle.test.ts` fail CI if a heading is invented. See `docs/universal-reader.md`.

**I-31. Enrichment concurrency comes from `OLLAMA_NUM_PARALLEL`, and enrichment cost is call count, not concurrency.**
Ollama serves that many requests at once and queues the rest, so a wider app-side semaphore overlaps nothing -- it moves the wait into Ollama's queue, where it counts against the caller's request timeout instead of being invisible. A `web_refs` call queued behind a 4.3k-token prompt burned its (then 180s) timeout, and the worker's backoff restarted the whole 200-section handler. `diagram_extractor` held a `Semaphore(3)` around a call in a serial `for` loop, so the 3 described nothing.

Measured, M3 Pro, llama3.2, 450-token generations:

| slots | 1 caller | 2 callers | 4 callers |
|---|---|---|---|
| 1 | 55.9 tok/s | 56.2 | 54.7 (per-call 4.5/8.9/13.5/17.8s) |
| 2 | 55.5 tok/s | 97.7 | 99.3 |

So size every semaphore *at* the slot count -- `get_enrichment_llm_semaphore()` for text, and `ENRICHMENT_VISION_CONCURRENCY` capped by it for vision. Each loaded model gets its own runner with its own slots, so text and vision do not contend.

- **Default 1.** A slot costs a full `OLLAMA_NUM_CTX` KV cache (896 MiB for a 3B model), and under 24GB the second competes with the 7B vision model for residency. Every install path sizes from physical RAM; the auto path never exceeds 2, and 4 is opt-in via `LUMINARY_PROFILE=performance` or `.env`.
- **`n_ctx_slot` stays 8192 at 2 slots** -- Ollama allocates `num_ctx * num_parallel` and divides -- so raising this does not violate I-27 and needs no `OLLAMA_CONTEXT_LENGTH`.
- **The desktop app has no install step**, so `supervisor.rs` sizes it at launch and passes the same number to Ollama *and* the backend; if they disagree the extra slots sit idle behind a narrower semaphore.
- **Call count is the real lever.** Prompt eval is ~0.4s against ~16s of decode, so one call per section scales with the book: `web_refs` cost ~50 of DDIA's ~80 enrichment minutes. `WEB_REFS_MAX_SECTIONS` caps coverage the way `section_summarizer.MAX_UNITS` does. Reach for fewer or cheaper calls before reaching for concurrency.
