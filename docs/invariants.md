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

**I-33. A citation excerpt is a quote the grounding contains. Nothing invents one.**
Measured on shipped 0.6.1 over 10 `book` questions: of 6 citation chips returned, 3 were absent
from the chunks the answer was generated from. One was the model's own narration of events
("After the mysterious disappearance of the time machine, everyone is silent for a moment"),
one was commentary about the retrieval itself ("The context does not provide specific details
about the physical layout of the dining area"), and one was real prose from the source that
retrieval never returned — recited from the model's own memory, so no chunk links to it. All
three render as a source chip indistinguishable from a real quote.

All five citation-bearing system prompts specified the field as a bare format example,
`"excerpt":"..."`, which states a shape and not a provenance, so the model fills it the way it
fills any free-text field. Nothing downstream could tell a quote from a sentence the model
wrote: `_split_response` only parses JSON, and `_enrich_citation_titles` matches on
(section_heading, page) and never on the excerpt text. The chunk-derived `source_citations` are
safe by construction — each carries a `chunk_id` and slices `section_preview_snippet` out of the
chunk — so two lists with opposite trustworthiness rendered side by side under the same answer.
The eval could not catch it either: `citation_support_rate` scored the commentary chip `yes`.

**Asking the model to copy the quote instead is not the fix, and measuring it is what showed
why.** Prompted to reproduce the passage verbatim and having its excerpt dropped when it did
not, the model stopped citing rather than risk the attempt: `citation_coverage` fell 0.750 →
0.5429 on `book` and 0.872 → 0.7632 on `paper` against bit-identical retrieval, while the
verification filter itself removed only 2 citations across all 80 questions. Trading a
fabricated quote for no quote is progress; trading a findable quote for no quote is not.

So the model never reproduces source text. `pack_context_indexed` labels each passage it emits
with an `[S<n>]` marker and returns the marker map, the model cites `{"source":"S1"}`, and
`_resolve_marker_citations` fills the excerpt from the chunk that marker names — verbatim by
construction, and carrying the `chunk_id` that makes the chip deep-linkable. Marker numbering
must come from the packer, because grouping, dedup and the token budget all decide which chunks
reach the prompt; numbering the input list instead points every citation at the wrong passage.
A `quote` the model offers is used only to locate a sentence inside that chunk, never as content.
**Which part of the chunk is shown is itself load-bearing.** A chunk is sized for the embedder, so
the sentence carrying the claim sits anywhere in it, and cutting the head shows the wrong text:
12 of 15 measured `book` chips were head cuts, and the same chips scored 0.5667 on their displayed
excerpt against 0.8667 judged on their full chunk. `_excerpt_from_chunk` therefore selects the
window by content overlap with the answer, weighting the model's `quote` above it. Anything that
scores the displayed excerpt — `citation_support_rate` above all — is measuring that selection as
much as the citation, which is why two structural fixes aimed at citation choice moved it barely
at all.
A marker naming no such passage is dropped. Citations still arriving as free-text excerpts (other
prompts, other models) stay on the verification path: a contiguous run of 8 normalised tokens
must appear in the grounding, loose enough to survive re-punctuation and ellipses, which an exact
string test is not. `tests/test_qa.py` and `tests/test_context_packer.py` fail CI if a marker
resolves to the wrong chunk, if an ungrounded excerpt survives, or if any of the five prompts
stops citing by marker.

**I-34. A flashcard's excerpt is a span of the passage the card was written from, and every card
records whether that was checked.**
The review screen prints `source_excerpt` under a heading that reads "Source". Measured on a
949-card library: of the 392 cards carrying a checkable quote, 102 (26%) quoted text absent from
their document — 66 of them with no recognisable span of the document in the quote at all — and
nothing in the product could tell them apart from the 289 that were real. Rewriting the prompt
does not fix this: prompt v2 scored 0.7300 factuality against v1's 0.7267 on the full golden,
because a model asked for a well-shaped card about a familiar text writes what it already
believes. Quoting is the part it cannot do from memory, so the check is on the quote.

Two generation paths were worse than unchecked. `flashcard_audit.fill_gaps` prompted with the
section *heading* and nothing else while its system prompt demanded a `source_excerpt`, so every
quote it produced was necessarily invented; `_generate_concept_cards` and `generate_from_graph`
each had the passage in scope and passed it to neither the gate nor the verdict. A card is
written from a passage or it is not written.

`grounding` is four states — `unchecked | verified | unsupported | unverifiable` — and not a
boolean, because "checked and found" and "nothing could be checked" are different answers and 59%
of that library is the second. A boolean makes an unaudited deck read clean, which is the whole
defect restated. `unsupported` is reserved for the strong claim: the card produced a quote and
that quote is not in the text. Existing rows default to `unchecked` rather than to a verdict, and
`POST /flashcards/grounding/audit` recomputes deterministically with no model in the loop; it
never overwrites a verdict it cannot re-derive, since a note-sourced card's verdict was decided
while the note text was in hand. The quote match tolerates whitespace, elision and one trailing
punctuation character — 4 of 129 rejections differed from the document by a single closing `.` or
`"` on a span otherwise verbatim to ~300 characters — and nothing more: `"...five moves on
average."` against a document containing none of it stays rejected. `tests/test_flashcard_grounding.py`
and `tests/test_flashcard_audit.py` fail CI if a fabricated quote is kept, if the gap-fill prompt
stops carrying the section text, or if a verdict is computed and dropped. See I-33 for the same
defect on the `/qa` surface, where the fix is different: an answer cites a marker and never
reproduces source text, which a flashcard cannot do because the quote *is* the card's evidence.

**I-35. A card's passage is what was in its prompt, and whatever judges that passage is not
the model that wrote the card, nor a model that has been shown to agree with everything.**
`flashcards.chunk_id` holds the first chunk of the generation *scope*. Nothing in the code says
so, and reading it as "the chunk this card came from" is the obvious mistake: judged against a
passage rebuilt that way, a 60-card sample scored `factuality 0.3333` — and the number was the
rebuild, not the cards. The judge had been shown text not containing the card's own verified
quote 56 times out of 60. `source_chunk_ids` records the chunks whose text actually reached the
prompt, in reading order, and it is the *sampled* subset: past `_CHUNK_CHAR_LIMIT`, `_build_text`
keeps a beginning/middle/end window and drops what is between, so recording the whole scope would
name text the model never saw. Three states stay distinguishable and none may be read as another:
recorded ids, `NULL` (predates the column, or a path with no chunks), and `[]` (supplied text —
real, but not reconstructible from the library). A card whose passage cannot be rebuilt is
**skipped and counted as skipped**, never judged against an approximation.

The second half is not derivable from any code, only from measurement, and it is the half that
will be undone to save memory. Whether an answer follows from a passage is semantic, so this is
the one flashcard check that needs a model — which makes the model the load-bearing choice.
Screened on 59 live cards with identical passages: `phi4-mini` returned `yes` for 54, `mistral`
and `granite3.2:8b` for 53, each agreeing with `qwen2.5:14b` on the pass/fail call 0.41–0.42,
which is worse than chance; `gemma3:4b` failed a four-case probe outright, certifying a card that
reversed who did what. Only `gemma4` (43/59) and the 14B (19/59) discriminate. So
`FLASHCARD_FACTUALITY_MODEL` has **no default** — an unnamed checker does not run, and cards stay
`unchecked`, which is honest where a rubber stamp is not. Every candidate is fired on the
four-case probe (supported / reversed / invented / off-topic) *and* at scale before it is
trusted; passing the probe is necessary and demonstrably not sufficient.

Self-judging is refused, and the guard must resolve the model that will actually generate rather
than the configured override. The override is empty on the default path, which is exactly where
the collision happens: with `LITELLM_DEFAULT_MODEL=ollama/qwen2.5:14b-instruct` and the same id
configured as the checker, the guard reported no self-judging and the audit judged the model's own
cards. `effective_generation_model()` resolves it; `scripts/smoke/S237.sh` refuses to measure when
they collide, and `tests/test_flashcard_factuality.py` and `tests/test_flashcard_passage.py` fail
CI if an unparseable verdict defaults to a pass, if a rebuilt passage falls back to `chunk_id`, or
if the guard reads the override again.

**I-36. A regeneration reads material the current deck was not written from, that deck is still
in the table while it runs, and one call replaces exactly one source.**
"Regenerate (replace)" returned the questions it had just deleted, and the deck came back two
cards short of the five it replaced. Nothing was cached and nothing was wrong with the decoding.
Measured on the reported document: 265 chunks, of which `_filter_chunks_by_classification` leaves
10, and all 10 fit `_CHUNK_CHAR_LIMIT` — so every run read the same 3,024 characters and returned
the same handful of topics reworded, whatever happened to the deck in between.

**What a generation can ask about is a property of the passage in its prompt.** The lever is which
chunks reach it — not the temperature, and not an instruction. The first fix listed the previous
questions under "do not repeat these", which is the I-28 anti-pattern in a new place: verbatim
questions are exemplars a small model copies, not a signal it steers away from. `source_chunk_ids`
(I-35) already records which chunks each card was written from, so `_passage_not_yet_used` drops
them and takes the next unread run of the document in reading order; successive regenerations
sweep forward rather than re-reading the opening. The replacement passage is held to the size of
the one it replaces instead of filling the budget — more text is not free. Three runs each on the
reported document: capped, 14 of 15 cards past the grounding gate and 4–5 delivered per run;
filling the budget with the same material, 12 of 15 and 3–5. Both shared no question with the deck
they replaced, so the cap costs no novelty.

**A note has no unread material, so its replacement is made different by rejection rather than
selection.** Filtering the extracted concepts on the previous questions was tried first and
measured useless: extraction returns whole sentences ("TF-IDF measures the importance of a word in
a document within a corpus"), which never occur inside a question, so on two real notes it dropped
0 of 12 and 0 of 11 — a check that cannot fire. What fires is the 0.85 cosine test already used on
document cards, scoped to the note being replaced: measured against a real 8-card note deck, three
rewordings of its own questions scored 0.9284, 0.9593 and 0.9828, while three genuinely new
questions about the same note scored 0.7627, 0.7730 and 0.8248. Extraction is widened during a
replacement so the run has spare concepts when candidates are rejected, which costs no extra call.

**A note card records which note wrote it, and only when one note did.** Cards from the
`note_ids` path carried no `note_id` at all — 75 such rows in the dev library — and
`collection_card_filter` matches on it, so a collection could not see, scope or delete them. Its
"Regenerate (replace)" wiped what the filter could find and then generated more, stacking a new
batch of note cards on top of the old ones every time. Several notes are concatenated into one
prompt, so a run over more than one records `NULL` rather than naming one of them: that is the
same false provenance `chunk_id` carried before I-35, and a card that cannot be attributed must
not be swept up by a replacement of some other note. Rows written before this stay `NULL` — the
note that produced them was never recorded, so nothing can recover it.

**The order is the other half, and it is what a client cannot get right.** The near-duplicate
filter compares a candidate against the cards the document already has, so deleting the deck first
left it comparing against nothing — the one mechanism that could catch a repeat was disabled by
the step before it, and a run that produced nothing left the user with an empty deck.
`POST /flashcards/regenerate` is therefore one request, and it takes exactly one source: a
collection replaces its sources one at a time, so a source whose run fails costs that source's
cards and no others. `requested` and `delivered` are both on the wire because they differ — the
quality gate drops a card whose quote is not in its passage and a backfill pass cannot always
replace it, which is how a deck of 5 came back as 3 announced as a clean replacement.
`tests/test_flashcard_regenerate_differs.py` fails CI if a replacement re-reads the chunks its
deck was written from, if it reads more than the passage it replaces, if a note run stops rejecting repeats of its own
deck or starts rejecting another note's cards as its own, if a single-note run stops recording
`note_id` or a multi-note run starts inventing one, if the old cards are deleted before new ones exist, if an empty run
deletes anything, or if a short delivery is not reported; `scripts/smoke/S243.sh` fails if the
endpoint stops taking either source, stops refusing two, stops reporting the three counts
separately, or if `avoid` returns to the generate request.

## Vector Dimensions

**I-9. Note and chunk vectors share one embedding space, whose dimension is a stored property of the corpus rather than a setting.**
The deployed embedder is `bge-small-en-v1.5` and the LanceDB schema must declare `pa.list_(pa.float32(), 384)` to match it. Notes and chunks share one embedder and one vector space, so a note vector is directly comparable to a chunk vector. Any table declaring a different dimension is a bug.

The embedder is therefore not pluggable the way a generation model is. Every stored vector was written by the deployed model, so replacing it is a full re-embed of the corpus behind a migration, not a config change — the dimension in the schema moves with it or nothing matches anything. Work that makes generation models substitutable must state explicitly that it stops here.

**The number is declared once, and the check is against the embedder rather than against the declaration.** `note_vectors_v2` carried a hand-written `NOTE_VECTOR_DIM = 1024`, and a 61-note library held **zero** note vectors: a 384-float list cannot be cast into a 1024 fixed-size list, so every `upsert_note_vector` raised and `embed_and_store_note` logged it "non-fatal" and returned. Semantic note search then returned nothing, which is indistinguishable from a library with no matching notes — so the chat notes path answered "Nothing in your library matches that question" about notes it held, and had done since the table was created. The existing guard in `_get_or_create_note_table` could not catch it: it compares the table against the constant, and both said 1024. A constant is not a check when the constant is what is wrong. One `EMBEDDING_DIM` now feeds every schema in the space, and `tests/test_vector_space_dimension.py` fails CI if any table declares something else **or if the deployed embedder stops producing that many dimensions**. Fixing the declaration does not backfill: the guard drops and recreates the table, and the vectors come back only via `ReindexService.reindex_notes`.

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
`make ci` runs `pytest` against the app in-process; it never starts a server, so it cannot catch a route registered in the wrong order, a router the manifest does not cover, or a response shape the UI reads differently than the test does. `scripts/smoke/all.sh` drives ~180 numbered `S###.sh` scripts against a live backend on :7820 and is the only thing that verifies the wire contract the frontend depends on. A change that adds or alters an endpoint is not finished until it has a smoke script and `make smoke` exits 0. There is no reviewer gate and no `passes=true` flag -- an earlier version of this invariant named both, and neither ever existed in the repo, so any claim of having satisfied them was unfalsifiable. If you want a review, `/code-review` is the mechanism.

**I-32. An eval metric that could not be computed is a failure, never a pass.**
`run_eval.py` scored every generation metric behind `if value is not None`, so an NLI model that failed to load, a judge that errored, or a `/qa` that timed out produced `None`, was skipped, and recorded `passed: true` for a run that measured nothing of what it was asked to measure. 166 rows in `scores_history.jsonl` were written under that rule, one of them a generation run whose faithfulness is null -- and history is what later comparisons are read against, so a pass that was never earned poisons every delta computed from it. The distinction the gate must keep is between **requested-but-uncomputed**, which fails, and **not-requested**, which is a skip: a retrieval-only run legitimately has no faithfulness, while a run that generated answers and could not score them has a hole in it. `_check()` in `run_eval.py` takes `requested=` for exactly this, and asking for generation while `/qa` returns no answers at all is itself a violation. Never paper over the gap with a default -- no `or 0.0`, no `or 1.0`, no neutral score for a missing verdict. `tests/test_eval_gate.py` fails CI if an uncomputed metric passes, or if a violation stops short of a non-zero exit. See the `eval-integrity` skill.

## Packages

**I-15. Use `uv` only -- never `pip` or `poetry`.**
The lockfile is `uv.lock`. Adding packages: `uv add <package>`. Never run `pip install` directly.

## Privacy & Local-First

**I-16. The default path is local: a fresh install works with no account, no key and no network.**
Ollama is the local runtime today and `WEB_SEARCH_PROVIDER` defaults to `none`. Neither name is the invariant — the invariant is that on-device inference and local search are the default path, and that every cloud provider is an opt-in alternative to a local path that already exists. Never introduce an external API dependency (Tavily, OpenAI, a hosted embedder) without shipping a local-first or privacy-preserving alternative alongside it. A feature that only works against a cloud provider does not ship as a default.

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

**I-27. One context window per loaded model, resolved from the model and never from the call site.**
A local runtime keys its loaded runner on generation geometry: Ollama reloads llama-server when a call asks for a different `num_ctx` (~1s idle, far worse under contention). The window is a property of the model, not of the caller. Three per-site windows -- 2048 default, 4096 QA, 8192 generation -- made a single chat turn reload the model twice and a question asked during ingestion reload it repeatedly.

The *value* belongs to the model and is read from its profile; the *rule* is that exactly one is in force for a loaded model at a time. Sizing it is a trade rather than a maximum: the window must fit the largest single prompt or that prompt is silently truncated, while every serving slot costs a full window of KV cache (I-31). A model advertising a 256K window is not a reason to ask for one — that number is a capability, not a budget.

**The value half was unbuilt until 2026-08-18.** `usable_context` sat on every registry entry unread while one global `OLLAMA_NUM_CTX` applied to every model at once, so a more capable model could not be given a larger window without giving it to everything, and a smaller model could not be given a smaller one to save the KV cache it does not need. `model_registry.context_window_for(model_id)` is now the only thing that decides a window: it returns the model's `usable_context`, falling back to `OLLAMA_NUM_CTX` only for a model with no registry entry, which a user may legitimately select. Resolving from the model is *stronger* than the global constant, not weaker — the window is a pure function of the model, so two call sites cannot disagree about it even by accident. `_summary_num_ctx` resolves the same way, because the same number both requests the window and sizes the summary's input budget; pinning one to the global while the other followed the profile would ask for one window, reload the runner, and then truncate against the other.

Changing a window is not free and not local: `resident_bytes` is weights plus one KV cache **measured at** `MEASURED_AT_NUM_CTX`, and that footprint is what decides whether a model is offered on a given machine. An entry whose window no longer matches what its footprint was measured at is reporting a memory cost the machine will not see — re-measure with `scripts/model_footprint.py` rather than editing the number. `tests/test_single_local_context_window.py` fails CI on a second knob, on any call site that *chooses* a window rather than plumbing or resolving one, on any module outside `config.py` and `model_registry.py` reading the global, on a window below the largest prompt, and on a window that diverges from the footprint's measurement point.

**I-28. A generation prompt states the shape of what it wants, never the name of a taxonomy.**
Suggested questions were generated by naming the Bloom level in the prompt ("6 questions at Bloom taxonomy level 5 (Evaluate)"). A label is not a specification: the model pattern-matches the word to the register it has seen it in, and the prompt returned exam papers -- "Evaluate how X's reliance on Y can be advantageous" -- which no reader would type and which trips I-26 by reading as a learner's explanation.

The reason this is an invariant rather than a fix is portability. What a label resolves to is a property of the model reading it, so a prompt built on one means something different on the next model, and the difference is invisible in any output-quality score. Stating the observable shape instead is what makes the prompt survive a model change. The level selects plain-language guidance in `_LEVEL_GUIDANCE`; the taxonomy word never reaches the model, and the wire key is `depth`, not `bloom_level`. The same rule covers few-shot context: prior questions reach the prompt as bare topic words (`_history_topics`), because injecting them verbatim under "avoid these" hands the model dozens of exemplars whose register it copies.

`tests/test_suggestions.py` fails if any taxonomy term reappears in a rendered prompt. That guard covers the suggestions surface only: `services/flashcard_prompts.py` still opens with "creating flashcards based on Bloom's Taxonomy" and enumerates L1-L6 by name, which is the same defect unguarded. Widening the guard to every rendered prompt requires a single render path to assert against.

**I-29. The reader never reconstructs prose from retrieval chunks.**
Chunks are sized for the embedder, not the eye: they cut mid-sentence, they overlap, and 90% of them contain no paragraph break at all (261 of 2,599 measured on `frankenstein` + `the_odyssey`). Re-joining them with `\n\n` fabricates a false paragraph break every few hundred characters and duplicates text at every overlap seam. Reading text comes from `sections.body`, which is uncapped; `sections.preview` is a 10,000-char snippet for section lists and flashcard context and is truncated mid-sentence on any longer section, so it is not reading text either. `GET /sections/{id}/content` returns `content_source` (`body` | `preview` | `chunks`) so a degraded tier is visible rather than silent -- `chunks` serves only documents ingested before the column existed, and those must be re-uploaded. `tests/test_section_content_reader.py` fails CI if the reader prefers a lossy tier over `body`. See `docs/universal-reader.md`.

**I-30. A heading is a label the source authored. Nothing invents one.**
The reader draws a section heading only when the stored `heading` is non-empty and reads like a label (`hasAuthoredHeading`); an unlabelled section is rendered without one. Three sites used to fabricate headings and each produced the same artifact -- an oversized `<h2>` printing text that then repeated immediately below it, or an empty section under a swallowed line. `universal_parser._segment` stored a whole matched line as the heading, which for a transcript IS the utterance (`_is_marker` now sends prose to the body); `_segment_chat_grouped` synthesised "Transcript Part 2: Carol", naming whichever speaker opened the group; and `chunk.py` substituted `f"Section {n}"` for every empty heading. An empty heading is the signal that the source gave none, so nothing downstream may fill it -- `sectionTitle()` still derives a label, but only for the contents panel, which needs an entry to navigate with. Empty-bodied sections are dropped rather than filled with placeholder text: a document's contents page matches the same signature as its chapter openings, so half the sections found in `the_odyssey.txt` (23 of 49) were empty twins that used to read "(Empty Section)". `tests/test_universal_parser.py` and `sectionTitle.test.ts` fail CI if a heading is invented. See `docs/universal-reader.md`.

**I-31. Concurrency comes from the runtime's serving width, and inference cost is call count, not concurrency.**
`OLLAMA_NUM_PARALLEL` is that width today. The runtime serves that many requests at once and queues the rest, so a wider app-side semaphore overlaps nothing -- it moves the wait into the runtime's queue, where it counts against the caller's request timeout instead of being invisible. A `web_refs` call queued behind a 4.3k-token prompt burned its (then 180s) timeout, and the worker's backoff restarted the whole 200-section handler. `diagram_extractor` held a `Semaphore(3)` around a call in a serial `for` loop, so the 3 described nothing.

Measured, M3 Pro, llama3.2, 450-token generations:

| slots | 1 caller | 2 callers | 4 callers |
|---|---|---|---|
| 1 | 55.9 tok/s | 56.2 | 54.7 (per-call 4.5/8.9/13.5/17.8s) |
| 2 | 55.5 tok/s | 97.7 | 99.3 |

So size every semaphore *at* the slot count -- `get_enrichment_llm_semaphore()` for text, and `ENRICHMENT_VISION_CONCURRENCY` capped by it for vision. Each loaded model gets its own runner with its own slots, so text and vision do not contend.

- **Default 1.** A slot costs a full `OLLAMA_NUM_CTX` KV cache (896 MiB for a 3B model), and under 24GB the second competes with the 7B vision model for residency. Every install path sizes from physical RAM; the auto path never exceeds 2, and 4 is opt-in via `LUMINARY_PROFILE=performance` or `.env`.
- **`n_ctx_slot` stays 8192 at 2 slots** -- Ollama allocates `num_ctx * num_parallel` and divides -- so raising this does not violate I-27 and needs no `OLLAMA_CONTEXT_LENGTH`.
- **The desktop app has no install step**, so `supervisor.rs` sizes it at launch and passes the same number to Ollama *and* the backend; if they disagree the extra slots sit idle behind a narrower semaphore.
- **The runtime does not preempt, but the client can cancel, and that does free the slot.** Admission decides whether to *start* a background call and cannot help once one is in flight: chat suggestions admitted at 11:51:20 were still running when a question arrived at 11:51:21, and 48.5s of that question's 102s time-to-first-token was spent behind them. Cancelling the HTTP request releases the slot immediately -- Ollama logs `srv stop: cancel task` and a call cancelled at 12.0s was followed by one served in 0.44s. So work that is cheap to lose and has a real fallback may be abandoned for a waiting user: `run_yielding_to_interactive` does this for suggestions, whose empty return already means "templates answer instead". Enrichment is NOT eligible -- abandoning a section summary throws away minutes and leaves no equivalent second answer. The timer arms only after interactive pressure has been seen to clear, because a background call *waiting* in admission is blocking nobody and abandoning it would spend suggestion quality on every host where a question outlasts the window. `tests/test_background_yields_the_slot_to_a_waiting_question.py` fails if a queued call is abandoned or an in-flight one is not.
- **Call count is the real lever.** Prompt eval is ~0.4s against ~16s of decode, so one call per section scales with the book: `web_refs` cost ~50 of DDIA's ~80 enrichment minutes. `WEB_REFS_MAX_SECTIONS` caps coverage the way `section_summarizer.MAX_UNITS` does. Reach for fewer or cheaper calls before reaching for concurrency.

**I-37. A model load is billed to whichever call provokes it, so a slow call is not evidence about the component that reported it.**
Ollama loads a model inside the first request that needs one, and LiteLLM's `ollama/` completion path does not surface `load_duration` — it maps only `prompt_eval_count` and `eval_count` into usage. Every `[perf]` timer in the chat graph is wall clock around an `await`, so on a host where a load is slow the first call after an eviction reports a duration made almost entirely of work that is not its own. Measured on an Intel i7-8850H in a 12GB Docker VM: a question that took 261s logged `[perf] classify_node LLM fallback took 94.10s`, while llama.cpp's own timings for that call were 189 prompt tokens in 6.05s and 4 generated tokens in 0.59s — 6.6s of classification behind an 87.5s model load. The classifier was searched twice and was never the cause. Loading `qwen3.5:4b` on that host measured anywhere from 9.59s to 155.45s against seconds on the Apple Silicon hosts this app is tuned on, which is why nothing upstream treats an eviction as an event worth avoiding. The spread does not reduce to page cache -- loads with the cache dropped came out 35.5s/21.7s against 48.9s/12.7s with it retained -- so a load here is not a cost to tune but one to stop paying. **Residency is therefore a measured property of the host, not a constant**: `warmup._warm_llm` times the first local generation at start-up -- a load when there is one to pay, start-up contention when there is not, and the two cannot be told apart from inside the app (a 91.07s probe paid no load at all) -- and `model_keepwarm` holds the model resident only where that measurement says local inference is expensive — never behind a CPU or platform check, which would be a guess about the cause rather than a measurement of the effect. `tests/test_model_stays_resident_where_a_reload_is_expensive.py` fails CI if the gate stops being a measurement, if the threshold rises past a real cold load, or if a host that reloads quickly is pinged at all.

**I-38. A drawing primitive larger than its page is a container from a reflowed source, and the measurement that says so must happen before clipping.**
`_cluster_drawings` recovers vector figures from PDFs that embed no raster image, which is the only way a LaTeX-authored paper yields figures at all. It read `SQL_Cookbook_2006` (128pp, generated from an EPUB-style flow) as **81 images, 79 of them full pages of body text**. The cause is one line of order: the wash guard clipped each primitive to the page *before* measuring it. That book's pages carry a single fill rectangle spanning the whole flow — 21,608pt tall on a 792pt page, up to 42.21x the page box — and clipped, it is exactly the page's text column at 0.765 of the page area, comfortably under `_MAX_FIGURE_PAGE_FRACTION`. So it passed, painted the entire column onto the occupancy grid, bridged with the code-listing wash into one component, and satisfied `_MIN_FIGURE_PRIMITIVES` with three primitives. Nothing in the code reads as wrong; the evidence that identifies the container is destroyed by the clip one line above the test. The two populations do not overlap and need no tuning — real ink on those pages tops out at 0.938x the page box, the smallest container measures 1.20x — which is why `_MAX_PRIMITIVE_PAGE_SPAN` is 1.05 and not a fitted number.

The cost is not cosmetic, because every recovered figure is a vision LLM call. On an Intel i7-8850H reading through Docker those ran 278-305s each against a hardcoded 300s ceiling, so the job **failed on whichever figure happened to land above it** after 34 minutes and four descriptions, having also starved section summarisation and flashcard generation of the one Ollama slot (I-31: call count is the lever). Seven hours of model time were queued to paraphrase text that ingestion had already chunked, embedded and indexed verbatim — and those paraphrases go into image search, so the work made retrieval worse.

Three things follow, each guarded. **Line shape, not text density, separates a figure from a bordered paragraph**: a paragraph's lines span the box that contains them and a diagram's labels do not. Density was tried first and is wrong — ResNet's Figure 2 is 0.212 text by area, denser than three of four SQL Cookbook callouts, and a coverage threshold drops it. Measured across 96 candidate regions from five documents, the full-width-line share runs 0.000-0.176 for real figures (ResNet Fig 2 at 0.143) against 0.333-1.000 for prose, so `_MAX_PROSE_LINE_SHARE` is 0.25; below `_MIN_PROSE_LINES` the guard refuses to judge, because a figure carrying one wide caption line would otherwise score 1.0. **Extraction retires what it no longer produces**, since deduping on content hash means a re-extract can only ever add, and the 79 stale rows could not otherwise be cleared without deleting the document — guarded on the extractor having actually run, because `extracted` is also empty when the file cannot be opened. **A re-extraction supersedes a pending `image_analyze`**, whose input set it is about to change: the worker runs a document's jobs sequentially, so left queued the analyze job runs first and the re-extract waits behind all 77 images it was going to delete. `tests/test_image_extractor.py` fails CI if a page of prose is recovered as a figure, if a labelled diagram is read as prose, if a failed extraction retires anything, or if the survivors of a prune are left with no job to describe them.

The vision ceiling is a host measurement, never a platform check (I-37): `VISION_TIMEOUT_SLOW_HOST_SECONDS` applies only where start-up measured local inference to be expensive, so an unmeasured or fast host keeps the 300s it always had.
