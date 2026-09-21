---
description: Luminary hard invariants. Each was learned from a real incident; each names the gate that enforces it.
---

# Luminary Invariants

Each entry is a rule no one would derive from the code, the incident that taught it, the mechanism
behind it, and the test that fails CI when it is broken. Coding conventions live in
`docs/patterns.md`; process rules in `CLAUDE.md`. Numbers are permanent: retired ones are listed at
the end with where they went.

## Async / Concurrency

**I-1. Never share an AsyncSession across `asyncio.gather` tasks.**
SQLAlchemy's AsyncSession is not safe for concurrent use. Give each concurrent task its own session, or serialise with `Semaphore(1)`.

**I-2. Wrap every synchronous LanceDB and Kuzu call, and any long CPU call, in `asyncio.to_thread`.**
The server runs one worker, so a blocking call stalls every request, not just its own. Measured: a 2ms `/tags/graph` took 8.5s behind one all-library `/graph` traversal; `parse_node` running `DocumentParser.parse` inline froze the loop for 44.9s on a 23MB PDF (3.96s once threaded). In `public` mode the backend also serves the SPA, so its route chunks stop arriving and clicks look dead. Kuzu is safe off-thread: `ThreadSafeKuzuConnection` serialises `execute()` under an RLock. `chunk`, `entity_extract` and `transcribe` are still inline.

**I-40. Shutdown time is decided by the work inside the loop's default executor, not by the tasks awaiting it.**
The backend suite hung at `8634011` with no summary line, in a different test each run. A 30s `run_in_executor` call held `TestClient.__exit__` for 30.3s with no pending task, which is why task-draining fixes never touched it. `asyncio.Runner.close()` ends in `shutdown_default_executor(THREAD_JOIN_TIMEOUT)`, and that constant is 300s; every `to_thread` (LanceDB, Kuzu, model loads) runs in that executor. The same join is on the real quit path, so `lifespan` ends in `_release_default_executor`: a 20s join, then detach. Unbounded, the desktop supervisor SIGKILLs a mid-write thread and leaves the Kuzu lock held. `tests/conftest.py` bounds the join at 30s and reports whose background work outlived it; a fixture that gathers cancelled tasks without a timeout is the same trap, bounded once in `tests/task_drain.py`. `tests/test_quit_is_bounded.py` (which restores the stdlib join before measuring) and `tests/test_testclient_teardown_is_bounded.py` fail CI if the bound goes. The recurring `test_e2e_upload` timeout is a different class (an idle loop, aiosqlite workers waiting on a dead loop's future): a green run is not evidence there.

## FTS5 / SQLite

**I-4. Do not filter FTS5 virtual tables with `WHERE unindexed_col = :val`.**
UNINDEXED columns are unreliable for equality on a large table. Query the content shadow table (`notes_fts_content WHERE c1 = :nid`; columns follow CREATE order) and delete by rowid (`DELETE FROM notes_fts WHERE rowid = :rowid`).

**I-23. Schema changes are Alembic revisions; the `ALTER TABLE` list in `db_init.py` is frozen.**
`models.py` is the source of truth and `make db-revision m="..."` generates the revision against a throwaway database: pointed at a long-lived one, autogenerate emits `drop_table()` for real user tables. `db_init.create_all_tables()` only lifts pre-Alembic databases to the baseline. `tests/test_schema_drift.py` builds its database by running the migrations; when it built one from `models.py` and compared it with `models.py`, deleting a revision still passed 3/3. A drift test whose fixture comes from the thing it checks agrees with itself.

## Answers, citations and headings

**I-33. A citation excerpt is a quote the grounding contains. Nothing invents one.**
On shipped 0.6.1, 3 of 6 citation chips over 10 `book` questions quoted text absent from the chunks the answer was built from (narration, commentary on retrieval, prose recited from memory), rendered like real quotes. Prompts specified `"excerpt":"..."`, a shape, not a provenance. Asking the model to copy verbatim is not the fix: it stopped citing (`citation_coverage` 0.750 to 0.5429 on `book`, 0.872 to 0.7632 on `paper`, identical retrieval). So the model never reproduces source text: `pack_context_indexed` labels passages `[S<n>]`, the model cites `{"source":"S1"}`, and `_resolve_marker_citations` fills the excerpt from that chunk. Marker numbers must come from the packer, because dedup and budget decide which chunks reach the prompt. A chunk is sized for the embedder, so which part is shown matters: 12 of 15 chips were head cuts, scoring 0.5667 against 0.8667 on the full chunk; `_excerpt_from_chunk` selects by overlap with the answer, and `citation_support_rate` measures that selection too. Free-text excerpts must match 8 contiguous normalised tokens of the grounding. `tests/test_qa.py` and `tests/test_context_packer.py` fail CI if a marker resolves to the wrong chunk, an ungrounded excerpt survives, or a prompt stops citing by marker.

**I-41. A citation owns the arrival scroll alone, and a scroll inside a `scroll-smooth` container reaches its target only with `behavior: "instant"`.**
A source chip for a passage in a 23K-word book marked it and left it off screen. Three effects (`DocumentReader` at 100ms and 150ms, `ReadView` at 200ms) scrolled the section heading to the top after the mark was centred; they stand down when citation words are present. Tailwind's `scroll-smooth` wins over `behavior: "auto"`: the mark closed from 7027px over 8.1s and a 3s retry stopped 3535px short. Sections mount lazily, so the scroll repeats until it stops moving (`lib/citation/settleIntoView`, guarded by `settleIntoView.test.ts`). Only a browser measures the result: `make verify-citation` is a manual gate, because the unit suite twice passed while the app showed nothing.

**I-29. The reader never reconstructs prose from retrieval chunks.**
Chunks cut mid-sentence, overlap, and 90% contain no paragraph break (261 of 2,599 on `frankenstein` + `the_odyssey`), so joining them fabricates breaks and duplicates seams. Reading text is `sections.body`; `sections.preview` is a 10,000-char snippet. `GET /sections/{id}/content` returns `content_source` (`body` | `preview` | `chunks`) so a degraded tier is visible. `tests/test_section_content_reader.py` fails CI if the reader prefers a lossy tier. See `docs/universal-reader.md`.

**I-30. A heading is a label the source authored. Nothing invents one.**
Three sites fabricated headings, each printing an oversized `<h2>` that repeated the text below it: `universal_parser._segment` stored a transcript utterance as a heading, `_segment_chat_grouped` synthesised "Transcript Part 2: Carol", `chunk.py` substituted `Section {n}`. An empty heading means the source gave none; only the contents panel derives a label (`sectionTitle()`). Empty-bodied sections are dropped: 23 of 49 in `the_odyssey.txt` were contents-page twins reading "(Empty Section)". `tests/test_universal_parser.py` and `sectionTitle.test.ts` fail CI if a heading is invented.

## Chat routing

**I-25. Scope decides WHERE to look, never WHAT was asked.**
Telling the classifier to prefer `summary` under scope `all` turned every bare topic into a summary request, while the same query under one document stayed `factual`. A node that cannot serve its intent returns `{"intent": "factual"}` and falls through to `search_node`, never a placeholder.

**I-26. The LLM intent classifier picks a retrieval strategy, never an interactive mode.**
`teach_back`, `socratic`, `notes` and `notes_gap` change what chat does with the message. They are right only when the phrasing asks for them, and `classify_intent_heuristic` catches that phrasing at 0.95 without the LLM, so any mode the LLM names is a misfire: an analysis question came back `teach_back` and got an empty grading card. `_llm_classify_fallback` chooses from `_LLM_SELECTABLE_INTENTS`; anything else becomes `factual`. A new mode needs keywords, not a looser whitelist.

**I-55. Every retrieval call inside the chat graph matches `search_node`'s depth and rerank setting.**
On shipped 0.12.0 a question whose answer was a section heading word for word got "not covered in your documents": "differ" is a relational keyword, so it routed to `graph_node`, whose supplement retrieval used half the depth and skipped reranking. One spurious edge was enough, because `_extract_entities_from_question` kept only the first word of "Inverted Index". `comparative_node` and `augment_node`'s graph branch had the same gap. `HybridRetriever.retrieve()` defaults `rerank=False`, so every caller must read `get_rerank_enabled` and pass it; a copied call site copies the omission. `test_chat_graph_nodes.py` fails CI if a chat-graph retrieval stops reading the toggle, shrinks `k`, or the entity regex returns to single words. Cross-side chunk duplication in `comparative_node` is narrowed, not gone.

**I-53. A provider and a model are stored apart and spent together, so choosing a provider without a model routes to another provider's model.**
`get_effective_routing` concatenates two settings rows. `EngineChoice` sends a provider and no model, so accepting it on a fresh install produced `anthropic/gpt-4o-mini`, and the first answer could not resolve. Neither half is wrong alone. A provider change now carries that provider's default model (`_PROVIDER_DEFAULT_MODEL`); re-sending the stored provider is not a change, and a model named in the same PATCH wins. `test_settings.py` fails CI if an offered provider resolves outside its own family, or a kept provider loses its model.

## Local models

**I-9. Notes, chunks and concepts share one embedding space, whose dimension is a stored property of the corpus, not a setting.**
Every schema declares `pa.list_(pa.float32(), EMBEDDING_DIM)` (384, `bge-small-en-v1.5`). Replacing the embedder is a full re-embed behind a migration. The check is against the embedder, never a declaration: `NOTE_VECTOR_DIM = 1024` made every note upsert raise, logged as non-fatal, and a 61-note library held zero note vectors while its guard compared the table with the same wrong constant. `tests/test_vector_space_dimension.py` fails CI if a table disagrees or the embedder stops producing that many dimensions. Fixing a declaration does not backfill; `ReindexService.reindex_notes` does.

**I-57. A running app never downloads model weights; only an explicit provisioning step does.**
Every loader fell back to downloading on a cache miss, per request: on a network blocking huggingface.co one smoke run sent ~235 blocked requests while ingest and search failed. Loaders are cache-only and raise `ModelNotDownloaded`; weights come from setup (`model_prefetch`, or `python -m app.services.model_prefetch`) or a component install (`transcription` fetches Whisper). A load during setup waits for that download (`require_snapshot`). `local_files_only=True` is not cache-only for GLiNER, whose bare `AutoTokenizer.from_pretrained` calls the hub unless forced offline; `offline_model_load` does that process-wide, so GLiNER first waits out in-flight downloads. A cached GLiNER checkpoint does not load alone: its tokenizer comes from the repo in `gliner_config.json`, which setup fetches and `snapshot_present` requires. `tests/test_no_runtime_download.py` fails CI if an empty-cache loader constructs anything, a cached load is not cache-only, or setup skips the tokenizer base.

**I-27. One context window per loaded model, resolved from the model and never from the call site.**
Ollama reloads the runner when a call asks for a different `num_ctx`; three per-site windows (2048, 4096, 8192) reloaded the model twice per chat turn. `model_registry.context_window_for(model_id)` alone decides a window, falling back to `OLLAMA_NUM_CTX` only for an unregistered model, and `_summary_num_ctx` resolves the same way because the number also sizes the summary's input. The window must fit the largest prompt, and every serving slot costs a full window of KV cache (I-31). `resident_bytes` is measured at `MEASURED_AT_NUM_CTX` and decides which models a machine is offered, so re-measure with `scripts/model_footprint.py` rather than editing it. `tests/test_single_local_context_window.py` fails CI on a second knob, a call site that chooses a window, a read of the global outside `config.py`/`model_registry.py`, a window below the largest prompt, or one off its footprint's measurement point.

**I-31. Concurrency comes from the runtime's serving width, and inference cost is call count, not concurrency.**
`OLLAMA_NUM_PARALLEL` is the width; a wider app semaphore only moves the wait into the runtime queue, where it counts against the caller's timeout. Four callers over 1 slot share 54.7 tok/s (done at 4.5/8.9/13.5/17.8s); over 2 slots, 99.3 (M3 Pro, llama3.2). Size semaphores at the slot count. Default 1, since a slot costs a full KV cache; every install path sizes from physical RAM, never a profile name (`>= 24 -> 2, else 1`), and the desktop `supervisor.rs` passes the same number to Ollama and the backend. The runtime does not preempt, but a client cancel frees the slot, so only work with a real fallback may yield to a waiting question (`run_yielding_to_interactive`, suggestions); enrichment may not. Prompt eval is ~0.4s against ~16s decode, so reach for fewer calls first: `web_refs` cost ~50 of DDIA's ~80 enrichment minutes. `test_installer_models.py::test_the_serving_width_band_agrees_across_every_install_path` and `test_background_yields_the_slot_to_a_waiting_question.py` guard it.

**I-37. A model load is billed to whichever call provokes it, so a slow call is not evidence about the component that reported it.**
Ollama loads inside the first request that needs a model and LiteLLM does not surface `load_duration`. A 261s question logged `classify_node ... 94.10s` while llama.cpp timed that call at 6.6s behind an 87.5s load (i7-8850H, 12GB Docker VM). Loads there ranged 9.59s to 155.45s, not explained by page cache, so residency is a measured property of the host, never a platform check: `warmup._warm_llm` times the first generation and `model_keepwarm` holds the model resident only where that says a load is expensive. `tests/test_model_stays_resident_where_a_reload_is_expensive.py` fails CI if the gate stops being a measurement or a fast-reloading host is pinged.

**I-39. A model's residency is what the runtime reports, never a process RSS, and every site that sizes the machine reads the same band.**
Peak minus backend RSS put `qwen3.5:4b` at 4.31GB (Ollama reports 3.21GB) and `qwen2.5vl:7b` at 8.77GB from a run that never loaded it; the pair read 102% of 16GB and `MAX_RESIDENT["standard"]` shipped at one model. From `/api/ps` the pair is 10.02GB. On unified memory RSS and Ollama's accounting disagree by design, and every `*_mb` field in `mem_profile.py` output is MB. `MAX_RESIDENT` is a permission; `fits_together` (`_RESIDENT_SET_FRACTION`) is the budget. `supervisor.rs` is a fourth sizing site no Python test could see, and it drifted when the floor moved to 16GB. `test_vision_role_resolution.py::test_a_standard_host_with_room_keeps_its_reader` and `test_installer_models.py::test_the_desktop_shell_agrees_about_the_residency_band` fail CI on narrowing or drift.

**I-28. A generation prompt states the shape of what it wants, never the name of a taxonomy.**
"6 questions at Bloom taxonomy level 5 (Evaluate)" returned exam-paper questions no reader would type, which also tripped I-26. What a label resolves to depends on the model, so a label-built prompt changes meaning across models invisibly. `_LEVEL_GUIDANCE` carries plain guidance, the wire key is `depth`, and prior questions reach prompts as bare topic words (`_history_topics`), never verbatim exemplars. `tests/test_suggestions.py` fails if a taxonomy term reaches a rendered prompt; `flashcard_prompts.py` still names L1-L6, unguarded.

**I-42. A list field from a model can arrive nested; normalise it where it enters, because the schema that rejects it fails a whole batch.**
`misconceptions` arrived as `[["...", "..."]]`: `GET /study/teachback/results` answered 500 for every card in the batched poll, and binding a list to `correction_note` rolled the score back to `error`. `_string_list` in `_parse_teachback_response` flattens one level and stringifies, never inventing a value. `test_practice_run_tally.py::test_list_fields_are_normalised_to_strings` guards it.

**I-43. Adding a free-text field to a JSON prompt changes its parse rate; prose asked for after numbers breaks a local model's quoting.**
Merging the teach-back rubric added a trailing `clarity_comment`, and scoring fell to 4/16 from 14/16 on paired servers; in isolation it parsed 12/12, so a harness run is not evidence here. The failures dropped the value's opening quote. Without the comment: 20/20 and 18/20 against 17/20 and 18/20, median wait 12.3s to 6.1s. Numbers after prose are safe. No free-text field joins `_TEACHBACK_USER_TMPL` without re-running the parse-rate arm.

## Flashcards and practice

**I-34. A flashcard's excerpt is a span of the passage the card was written from, and every card records whether that was checked.**
In a 949-card library, 102 of 392 checkable quotes (26%) were absent from their document; prompt rewrites did not help (factuality 0.7300 against 0.7267). `fill_gaps` prompted with a heading alone, and two graph paths never checked their passage: a card is written from a passage or not at all. `grounding` has four states (`unchecked | verified | unsupported | unverifiable`) because 59% of that library could not be checked, and a boolean makes that read clean. `POST /flashcards/grounding/audit` recomputes without a model. The match tolerates whitespace, elision and one trailing punctuation mark (4 of 129 rejections differed by a closing `.` or `"`). `tests/test_flashcard_grounding.py` and `tests/test_flashcard_audit.py` guard it.

**I-35. A card's passage is what was in its prompt, and it is judged by neither the model that wrote it nor one that agrees with everything.**
`flashcards.chunk_id` is the first chunk of the generation scope; judging against a passage rebuilt from it scored 0.3333, with the card's own verified quote missing 56 times in 60. `source_chunk_ids` records the chunks that reached the prompt (the sampled window past `_CHUNK_CHAR_LIMIT`); ids, `NULL` and `[]` are distinct, and an unrebuildable card is skipped and counted. On 59 cards `phi4-mini`, `mistral` and `granite3.2:8b` said yes to 53-54 and agreed with `qwen2.5:14b` 0.41-0.42; `gemma3:4b` passed a reversed card. So `FLASHCARD_FACTUALITY_MODEL` has no default and an unnamed checker leaves cards `unchecked`. Fire candidates on the four-case probe and at scale. Self-judging is refused against `effective_generation_model()`, not the override, which is empty on the default path. `scripts/smoke/S237.sh`, `tests/test_flashcard_factuality.py` and `tests/test_flashcard_passage.py` guard it.

**I-36. Generating more reads material the deck was not written from; a regeneration replaces exactly one source, and the deck stays until its replacement exists.**
"Regenerate (replace)" returned the questions it had deleted: filtering left 10 of 265 chunks, all under the char limit, so every run read the same 3,024 characters. "Add more" answered "No cards came back" on a document with 18 of 26 passages untouched, and both new cards came from exactly the eight chunks the deck was written from. What a generation can ask is a property of its passage; "do not repeat these" lists are exemplars (I-28). `_passage_not_yet_used` takes the next unread run, held to the replaced passage's size (no novelty cost measured). `avoid_used_material` is opt-in and ignored for a selection. Notes have no unread material, so their replacements differ by the note-scoped 0.85 cosine (rewordings 0.93-0.98, new 0.76-0.82); a card records `note_id` only when one note wrote it. `POST /flashcards/regenerate` takes one source, deletes nothing before new cards exist, and reports `requested` and `delivered`. `GET /flashcards/{id}/headroom` hides "add more" only when nothing is left, never on a failed request, a chunkless document or pre-`source_chunk_ids` cards. `test_flashcard_regenerate_differs.py`, `test_material_headroom.py`, `practiceDeck.test.ts` and `scripts/smoke/S243.sh` guard it.

**I-45. An evaluator is told the question, given only the passage the card came from, and never asked for a headline beside the breakdown it summarises.**
Teach-back graded against the whole passage, never saw the question, and read another card's window 38% of the time (`source_chunk_ids` is per call, not per card). `run_containing` picks the contiguous run holding the card's verified quote; when nothing locates, seams are marked `[...]`. The headline was a fourth integer: 24 of 90 verdicts fell outside their own dimensions, and 5 learners were told "Good explanation!" while both dimensions failed. `_score_from_dimensions` is `0.6*accuracy + 0.4*completeness` with `_DIMENSION_FLOOR`; clarity is shown but not counted. The integers stay last (I-43): 34/40 parsed before, 40/40 after. `test_teachback_passage_scope.py`, `test_teachback_grounding.py`, `test_teachback_rubric.py::test_score_from_dimensions` and `latestAttempts.test.ts` guard it.

**I-47. Cards and attempts are different counts, and a deleted card leaves both sides of "N of M reviewed".**
The header read "4 of 3" (a re-answered card counted twice), then "30 of 15" on resume (`reattach` took `max(prevResults.length, answered_count)` across attempts and cards; the max must stay, over distinct cards), then "7 of 8" on a three-card document because the plan kept ids of cards a replacement deleted. Planned means planned and still there: `GET /sessions/{id}/remaining-cards` counts only ids that resolve. A continuous run accumulates attempts indefinitely, so the guard is on the rendered ratio: `verify-dock`'s `checkProgressHeader` takes its cap from `GET /flashcards/{document_id}`, not the endpoint that built the header. `studySessionService.test.ts` and `test_practice_run_tally.py::test_a_replaced_deck_leaves_the_run_no_phantom_progress` fail CI otherwise.

**I-48. One generation call may not ask the same thing twice, judged on the answer too, and only within that call.**
A replaced deck returned two cards asking the same thing at question cosine 0.8014, under the 0.85 bar, which caught a within-call repeat zero times in 221 calls. `_repeats_this_call` refuses question >= 0.78 and answer >= 0.75, bracketed by the pair at 0.8014/0.7614 (refused) and 0.7890/0.7410 (kept). Applied to the whole deck the same bars refuse a median 19.1% of every document's cards; within a call, 3.8%. Batches are now checked against themselves even on an empty deck. `test_flashcard_duplicate_rule.py` guards the bars, the scope, and the first batch.

**I-49. A pair of one entity is not a relationship, and co-occurrence weight grows fastest on what a document repeats most.**
A graph card asked how "the two mentions of Ulysses" connect: ('ulysses','ulysses') at weight 62.0 topped `the_odyssey`. `canonical_entities` has one row per mention, so a chunk naming him twice paired him with himself; 8,235 of 74,376 CO_OCCURS edges (11.1%) are self-pairs, and direction followed mention order. Existing libraries will not be re-ingested, so reads exclude self-pairs and fold directions, `add_co_occurrence` refuses them, and `generate_from_graph` drops pairs with matching names. RELATED_TO holds zero edges; every graph card comes from co-occurrence. `test_entity_cooccurrence.py`, `test_graph.py` and `test_flashcard_from_graph.py` guard it.

**I-50. A question that points at its source cannot be answered away from it; key the gate on the referent, not a phrase list.**
The gate held sixteen phrasings and missed "the provided context"; 31 of 1234 cards pointed at their source in uncovered wording. The rule matches a source noun under a pointer: a demonstrative, a hand-over qualifier, an attribution preposition, or the source as speaker. Bare "the document" and "in the context of" are ordinary vocabulary and stay allowed. The rule refuses 35 of 1234 (2.8%), each read by hand; the sixteen phrasings remain for "the author" and "this example". `test_flashcard_quality_gate.py` guards both directions.

**I-52. Emptying a deck deletes the runs it emptied and none of their review events.**
A three-card document listed four dead runs after a replacement. `delete_session_cascade` takes a session's `review_events`, which are the learner record (`progress_service` streaks and accuracy key on `reviewed_at` alone); `_CARD_CHILD_TABLES` and `_LEARNER_RECORD_TABLES` already keep them. `purge_runs_without_live_cards` deletes the session row and results only where nothing planned survives, inside the request that deletes the cards (replace, delete all, selected, single); a partial delete leaves other runs alone. `test_regenerate_session_purge.py` and `test_card_delete_session_purge.py` guard it.

## Knowledge layer

**I-19. Mastery is a stored scalar on the concept row, never recomputed by text match, never on documents or collections.**
The assessment pipeline writes `concepts.mastery`; collection numbers are rollups. The old `chunk.text ILIKE '%name%'` computation is gone. See `docs/concepts.md`.

**I-20. The concept vector is derived and never a retrieval primary.**
`concept_vectors_v1` holds the centroid of a concept's evidence-chunk embeddings in chunk space (I-9), recomputed when evidence changes. Use it for concept similarity (linking, dedup, seeding, scope); chunk vectors, FTS5 and the graph (RRF) stay the RAG backbone.

**I-21. OKF is a projection, never a transport and never a source of truth.**
OKF files regenerate from SQLite and Kuzu; a user edit re-enters only as an `override`, re-applied after re-parse like a graph rename. See `docs/concepts.md`.

**I-22. A rejected or edited graph element does not reappear after re-parse.**
Re-parse proposes afresh, then `applyOverrides()` re-applies every user decision; rejections stay hidden, not deleted.

**I-24. Never add code that clears a Kuzu lock or kills its holder.**
The kernel releases Kuzu's exclusive file lock the instant the holder dies (verified against SIGKILL), so a stale lock cannot exist and "clear the stale lock" can only kill a live writer mid-write. A held lock is a real second process: surface it. A hand-rolled lockfile is worse, because it can go stale. This is a POSIX statement; Windows locks are mandatory (roadmap, 0.13.0).

## Ingestion

**I-38. A drawing primitive larger than its page is a container from a reflowed source, measured before clipping.**
`_cluster_drawings` read `SQL_Cookbook_2006` as 81 figures, 79 of them pages of text: a 21,608pt fill clipped to a 792pt page measures 0.765 of it, under `_MAX_FIGURE_PAGE_FRACTION`. Real ink tops out at 0.938x the page, containers start at 1.20x, so `_MAX_PRIMITIVE_PAGE_SPAN` is 1.05. Each false figure cost a 278-305s vision call against a 300s ceiling, starving the one Ollama slot (I-31). Line shape separates figures from bordered prose (full-width-line share 0.000-0.176 against 0.333-1.000, `_MAX_PROSE_LINE_SHARE` 0.25), not text density. Extraction retires what it no longer produces only on a complete pass (`ExtractionOutcome.skipped`), and a re-extract supersedes a pending `image_analyze`. `tests/test_image_extractor.py` guards all four.

## Quality gates

**I-32. An eval metric that could not be computed is a failure, never a pass.**
`run_eval.py` skipped `None` metrics and recorded `passed: true` for runs that measured nothing; 166 `scores_history.jsonl` rows were written that way. Requested-but-uncomputed fails; not-requested is a skip (`_check(requested=)`). No `or 0.0`, no `or 1.0`. Inputs too: `search_chunks` returned `[]` on a timeout, so a loaded host read HR@5 0.0000; a failed search now raises and leaves every retrieval rate `None` (`arm_metrics`). `tests/test_eval_gate.py` and `tests/test_eval_search_failures.py` guard it. See the `eval-integrity` skill.

## Privacy & Local-First

**I-16. The default path is local: a fresh install works with no account, no key and no network.**
Every cloud provider is an opt-in alternative to a local path that already exists; no external API ships as a default without one.

**I-18. User content never reaches external telemetry, and every library's phone-home is switched off.**
Phoenix and Langfuse run locally and carry trace structure, not content. `litellm.telemetry = False` left a second phone-home on: `import litellm` fetches a price list from raw.githubusercontent.com on every start unless `LITELLM_LOCAL_MODEL_COST_MAP` is set, and falls back silently when blocked. Such switches are read at the library's own import, so they are set in `app/__init__.py`. `tests/test_no_runtime_download.py` fails CI if they are unset.

**I-51. A macOS permission is enforced only in the signed bundle, and a missing usage string terminates rather than denies.**
Dictation worked under `tauri dev`, which inherits the terminal's grant and skips the hardened runtime; the `.app` had neither `NSMicrophoneUsageDescription` nor `com.apple.security.device.audio-input`. Without the usage string TCC kills the process at `getUserMedia`. Tauri merges `src-tauri/Info.plist` into the bundle's; an entitlements plist may carry no XML comment (`AMFIUnserializeXML: syntax error`). `verify_signed.sh` checks both on the built artefact. A feature reaching a camera, files outside the container, or the network in a new way needs the same pair.

## Cross-platform

**I-54. `os.kill` is not a liveness probe on Windows: every signal but a console event terminates the target.**
CPython maps `os.kill` onto TerminateProcess for everything but `CTRL_C_EVENT`/`CTRL_BREAK_EVENT`, which reach only console processes, so `os.kill(parent_pid, 0)` kills the shell it asks about and `os.kill(os.getpid(), SIGTERM)` skips `lifespan`. Branch, do not port: `OpenProcess` plus `GetExitCodeProcess` to ask, `signal.raise_signal` to stop. Found by reading CPython's contract, not an incident. `tests/test_parent_watch.py` pins both platforms.

**I-56. Reported RAM is installed RAM minus reservations on every OS but macOS, so every site that converts it to GB rounds up.**
A 16 GiB AWS g4dn.xlarge reported 15GB and was refused local inference (#139): all five readers truncated (`memory_profile.host_ram_gb`, `install.sh`, `install.ps1`, `bootstrap.sh`, `supervisor.rs`), and macOS's exact `hw.memsize` hid it. The reported figure never exceeds installed, so rounding up errs safely (Docker's 7.7 GiB VM is 8, still refused). `test_host_support.py::test_the_floor_reads_the_bytes_the_os_reports` and `test_installer_models.py::test_every_ram_reader_rounds_up` guard it.

## Retired numbers

Kept so existing references resolve.

| # | Now |
|---|---|
| I-3 | `patterns.md`: guard Kuzu `get_next()` with `has_next()` |
| I-5, I-6 | `patterns.md`: lazy imports for cycles; `get_settings` at module level |
| I-7 | `patterns.md`: persist before LLM calls in SSE generators, explicit rollback |
| I-8, I-10, I-11, I-12 | `patterns.md`, Frontend |
| I-13, I-14 | `CLAUDE.md`: `make ci` is the gate, `make smoke` the wire contract |
| I-15 | `CLAUDE.md` and a `.claude` hook: `uv` only |
| I-17 | merged into I-18 |
| I-44 | merged into I-36 |
| I-46 | merged into I-47 |
