---
description: Luminary hard invariants. Each was learned from a real incident; each names the gate that enforces it.
---

# Luminary Invariants

Each entry is a rule no one would derive from the code, the mechanism behind it, and the test that
fails CI when it is broken. The incident that taught it is in git history. Coding conventions live in
`docs/patterns.md`; process rules in `CLAUDE.md`. Numbers are permanent: retired ones are listed at
the end with where they went.

## Async / Concurrency

**I-2. Wrap every synchronous LanceDB and Kuzu call, and any long CPU call, in `asyncio.to_thread`.**
One worker serves every request, and in `public` mode the SPA's route chunks too, so a blocking call
stalls the whole app (a 23MB PDF parsed inline froze the loop for 44.9s). Kuzu is safe off-thread:
`ThreadSafeKuzuConnection` serialises `execute()`. `chunk`, `entity_extract` and `transcribe` are still
inline.

**I-40. Shutdown time is decided by the work inside the loop's default executor, not by the tasks awaiting it.**
`asyncio.Runner.close()` joins the default executor for up to 300s, and every `to_thread` runs there,
so task-draining fixes never bound a quit. `lifespan` ends in `_release_default_executor` (20s join,
then detach); unbounded, the desktop supervisor SIGKILLs a mid-write thread and leaves the Kuzu lock
held. Fixtures bound the join at 30s (`tests/conftest.py`, `tests/task_drain.py`).
`tests/test_quit_is_bounded.py` and `tests/test_testclient_teardown_is_bounded.py` fail CI otherwise.
The recurring `test_e2e_upload` timeout is a different class (aiosqlite workers waiting on a dead
loop's future): a green run is not evidence there.

## SQLite

**I-23. Schema changes are Alembic revisions; the `ALTER TABLE` list in `db_init.py` is frozen.**
`make db-revision` autogenerates against a throwaway database; against a long-lived one it emits
`drop_table()` for real user tables. `tests/test_schema_drift.py` builds its database by running the
migrations: built from `models.py`, it agreed with itself and passed with a revision deleted.

## Answers, citations and headings

**I-33. A citation excerpt is a quote the grounding contains. Nothing invents one.**
The model never reproduces source text: `pack_context_indexed` labels passages `[S<n>]`, the model
cites `{"source":"S1"}`, and `_resolve_marker_citations` fills the excerpt from that chunk. Marker
numbers come from the packer, because dedup and budget decide which chunks reach the prompt.
`_excerpt_from_chunk` picks the span by overlap with the answer (a head cut scored 0.57 against 0.87).
A free-text excerpt must match 8 contiguous normalised tokens of the grounding. Asking the model to
copy verbatim instead made it stop citing. `tests/test_qa.py` and `tests/test_context_packer.py` guard it.

**I-41. A citation owns the arrival scroll alone, and a scroll inside a `scroll-smooth` container reaches its target only with `behavior: "instant"`.**
Section-heading scrolls in `DocumentReader` and `ReadView` stand down when citation words are
present. Tailwind's `scroll-smooth` overrides `behavior: "auto"`, and sections mount lazily, so the
scroll repeats until it stops moving (`lib/citation/settleIntoView`, `settleIntoView.test.ts`).
`make verify-citation` is the gate, because the unit suite passed twice while the app showed nothing.

**I-29. The reader never reconstructs prose from retrieval chunks.**
Chunks cut mid-sentence and overlap, so joining them fabricates breaks and duplicates seams. Reading
text is `sections.body`; `GET /sections/{id}/content` reports `content_source` (`body` | `preview` |
`chunks`) so a degraded tier is visible. `tests/test_section_content_reader.py` guards it.

**I-30. A heading is a label the source authored. Nothing invents one.**
An empty heading means the source gave none; only the contents panel derives a label
(`sectionTitle()`). Empty-bodied sections are dropped. `tests/test_universal_parser.py` and
`sectionTitle.test.ts` fail CI if a heading is invented.

## Chat routing

**I-25. Scope decides WHERE to look, never WHAT was asked.**
A node that cannot serve its intent returns `{"intent": "factual"}` and falls through to
`search_node`, never a placeholder.

**I-26. The LLM intent classifier picks a retrieval strategy, never an interactive mode.**
`teach_back`, `socratic`, `notes` and `notes_gap` are right only when the phrasing asks for them, and
`classify_intent_heuristic` catches that at 0.95 without the LLM, so a mode the LLM names is a
misfire. `_llm_classify_fallback` chooses from `_LLM_SELECTABLE_INTENTS`; anything else is `factual`.
A new mode needs keywords, not a looser whitelist.

**I-55. Every retrieval call inside the chat graph matches `search_node`'s depth and rerank setting.**
`HybridRetriever.retrieve()` defaults `rerank=False`, so a copied call site copies the omission: a
`graph_node` supplement at half depth, unreranked, answered "not covered" to a question whose answer
was a heading. Every caller reads `get_rerank_enabled`. `test_chat_graph_nodes.py` fails CI if a
chat-graph retrieval stops reading it, shrinks `k`, or the entity regex returns to single words.

**I-53. A provider and a model are stored apart and spent together, so choosing a provider without a model routes to another provider's model.**
A provider change carries that provider's default model (`_PROVIDER_DEFAULT_MODEL`); re-sending the
stored provider is not a change, and a model named in the same PATCH wins. `test_settings.py` fails
CI if an offered provider resolves outside its own family.

## Local models

**I-9. Notes, chunks and concepts share one embedding space, whose dimension is a stored property of the corpus, not a setting.**
Every schema declares `EMBEDDING_DIM` (384, `bge-small-en-v1.5`); replacing the embedder is a full
re-embed behind a migration. The check is against the embedder, never a declaration: a wrong
constant made every note upsert fail while its guard compared against the same constant.
`tests/test_vector_space_dimension.py` guards it; `ReindexService.reindex_notes` backfills.

**I-57. A running app never downloads model weights; only an explicit provisioning step does.**
Loaders are cache-only and raise `ModelNotDownloaded`; weights come from setup (`model_prefetch`) or a
component install. `local_files_only=True` is not cache-only for GLiNER, whose tokenizer calls the hub
unless forced offline (`offline_model_load`), and its tokenizer comes from the repo named in
`gliner_config.json`, which setup must fetch. `tests/test_no_runtime_download.py` guards it.

**I-58. A running app contacts a third party only for something the user asked for, or with web access enabled.**
Link checks go through `reference_validator.link_checks_enabled()`, off while `WEB_SEARCH_PROVIDER`
is `none`. Fetching a URL the user submitted is asked for.
`tests/test_reference_validator.py::test_no_link_check_without_web_access` and
`tests/test_reference_enricher.py::test_no_http_calls_when_provider_none` guard it.

**I-27. One context window per loaded model, resolved from the model and never from the call site.**
Ollama reloads the runner when `num_ctx` changes, so per-site windows reloaded the model twice per
turn. `model_registry.context_window_for(model_id)` alone decides, and nothing outside `config.py` and
`model_registry.py` reads `OLLAMA_NUM_CTX`. The window must fit the largest
prompt, and every serving slot costs a full window of KV cache (I-31). `resident_bytes` is measured
at `MEASURED_AT_NUM_CTX`: re-measure with `scripts/model_footprint.py`, never edit it.
`tests/test_single_local_context_window.py` guards it.

**I-31. Concurrency comes from the runtime's serving width, and inference cost is call count, not concurrency.**
`OLLAMA_NUM_PARALLEL` is the width; a wider app semaphore only moves the wait into Ollama's queue,
against the caller's timeout. Admission caps background calls at the width and admits in arrival
order; `awaited()` puts a background-routed call someone is waiting on first (`background=True`
decides routing, not priority). Only work with a real fallback may yield to a waiting question
(`run_yielding_to_interactive`). Every install path sizes the width from physical RAM (`>= 24 -> 2,
else 1`), and `supervisor.rs` passes the same number to both processes. Reach for fewer calls before
more width. `test_installer_models.py`, `test_background_yields_the_slot_to_a_waiting_question.py`
and `test_llm_admission.py` guard it.

**I-37. A model load is billed to whichever call provokes it, so a slow call is not evidence about the component that reported it.**
LiteLLM does not surface Ollama's `load_duration`. Residency is a measured property of the host:
`warmup._warm_llm` times the first generation, and `model_keepwarm` holds the model only where a load
is expensive. `tests/test_model_stays_resident_where_a_reload_is_expensive.py` guards it.

**I-39. A model's residency is what the runtime reports, never a process RSS, and every site that sizes the machine reads the same band.**
On unified memory RSS and Ollama's `/api/ps` disagree by design. `MAX_RESIDENT` is a permission;
`fits_together` is the budget. `supervisor.rs` is a sizing site no Python test sees.
`test_vision_role_resolution.py` and
`test_installer_models.py::test_the_desktop_shell_agrees_about_the_residency_band` guard it.

**I-28. A generation prompt states the shape of what it wants, never the name of a taxonomy.**
What a label like "Bloom level 5" means depends on the model, so the prompt changes meaning across
models invisibly. Prior questions reach prompts as bare topic words (`_history_topics`), never
verbatim exemplars. `tests/test_suggestions.py` guards it; `flashcard_prompts.py` still names L1-L6.

**I-43. Adding a free-text field to a JSON prompt changes its parse rate; prose asked for after numbers breaks a local model's quoting.**
A trailing comment field dropped teach-back parsing from 14/16 to 4/16 on paired servers while
parsing 12/12 in isolation. Numbers go after prose. No free-text field joins
`_TEACHBACK_USER_TMPL` without re-running the parse-rate arm at scale.

## Flashcards and practice

**I-34. A flashcard's excerpt is a span of the passage the card was written from, and every card records whether that was checked.**
A card is written from a passage or not at all. `grounding` has four states (`unchecked | verified |
unsupported | unverifiable`), because a boolean reads an uncheckable library as clean. The match
tolerates whitespace, elision and one trailing punctuation mark. `POST /flashcards/grounding/audit`
recomputes without a model. `tests/test_flashcard_grounding.py` and `tests/test_flashcard_audit.py`
guard it.

**I-35. A card's passage is what was in its prompt, and it is judged by neither the model that wrote it nor one that agrees with everything.**
`source_chunk_ids` records the chunks that reached the prompt (ids, `NULL` and `[]` are distinct);
`chunk_id` is only the scope's first chunk. Small judges said yes to 53 of 59 cards, so
`FLASHCARD_FACTUALITY_MODEL` has no default and an unnamed checker leaves cards `unchecked`.
Self-judging is refused against `effective_generation_model()`. `scripts/smoke/S237.sh`,
`tests/test_flashcard_factuality.py` and `tests/test_flashcard_passage.py` guard it.

**I-36. Generating more reads material the deck was not written from; a regeneration replaces exactly one source, and the deck stays until its replacement exists.**
`_passage_not_yet_used` takes the next unread run, sized like the replaced passage. Notes have no
unread material, so their replacements must differ by the note-scoped 0.85 cosine (rewordings
0.93-0.98, new cards 0.76-0.82). `POST /flashcards/regenerate` deletes nothing before new cards
exist and reports `requested` and `delivered`; `GET /flashcards/{id}/headroom` hides "add more" only
when nothing is left. `test_flashcard_regenerate_differs.py`, `test_material_headroom.py`,
`practiceDeck.test.ts` and `scripts/smoke/S243.sh` guard it.

**I-45. An evaluator is told the question, given only the passage the card came from, and never asked for a headline beside the breakdown it summarises.**
`run_containing` picks the contiguous run holding the card's verified quote (`source_chunk_ids` is per
call, not per card). A model-given headline contradicted its own dimensions in 24 of 90 verdicts, so
`_score_from_dimensions` computes it (`0.6*accuracy + 0.4*completeness`, `_DIMENSION_FLOOR`).
`test_teachback_passage_scope.py`, `test_teachback_grounding.py`, `test_teachback_rubric.py` and
`latestAttempts.test.ts` guard it.

**I-47. Cards and attempts are different counts, and a deleted card leaves both sides of "N of M reviewed".**
The header counts distinct cards, and planned means planned and still there:
`GET /sessions/{id}/remaining-cards` counts only ids that resolve. `verify-dock`'s
`checkProgressHeader` takes its cap from `GET /flashcards/{document_id}`, not the endpoint under
test. `studySessionService.test.ts` and `test_practice_run_tally.py` guard it.

**I-48. One generation call may not ask the same thing twice, judged on the answer too, and only within that call.**
`_repeats_this_call` refuses question cosine >= 0.78 and answer >= 0.75, bracketed by 0.8014/0.7614
(refused) and 0.7890/0.7410 (kept). Deck-wide, the same bars refuse a median 19.1% of a document's
cards; within a call, 3.8%. `test_flashcard_duplicate_rule.py` guards the bars and the scope.

**I-49. A pair of one entity is not a relationship, and co-occurrence weight grows fastest on what a document repeats most.**
`canonical_entities` has a row per mention, so a chunk naming someone twice paired them with
themselves (11.1% of edges). `add_co_occurrence` refuses self-pairs, reads exclude them and fold
directions, and `generate_from_graph` drops same-name pairs. Stored edges from older ingests remain
(#161). `test_entity_cooccurrence.py`, `test_graph.py` and `test_flashcard_from_graph.py` guard it.

**I-50. A question that points at its source cannot be answered away from it; key the gate on the referent, not a phrase list.**
The rule matches a source noun under a pointer (a demonstrative, a hand-over qualifier, an
attribution preposition, or the source as speaker). Bare "the document" and "in the context of" stay
allowed. It refuses 2.8% of cards, each read by hand. `test_flashcard_quality_gate.py` guards both
directions.

**I-52. Emptying a deck deletes the runs it emptied and none of their review events.**
`review_events` are the learner record. `purge_runs_without_live_cards` deletes a session only when
nothing it planned survives, inside the request that deletes the cards.
`test_regenerate_session_purge.py` and `test_card_delete_session_purge.py` guard it.

## Knowledge layer

**I-24. Never add code that clears a Kuzu lock or kills its holder.**
The kernel releases Kuzu's lock the instant the holder dies, so a stale lock cannot exist and
"clearing" one can only kill a live writer mid-write. A held lock is a real second process: surface
it. This is a POSIX statement; Windows locks are mandatory (roadmap, 0.13.x).

## Ingestion

**I-38. A drawing primitive larger than its page is a container from a reflowed source, measured before clipping.**
`_MAX_PRIMITIVE_PAGE_SPAN` is 1.05, bracketed by real ink at up to 0.938x the page and containers
from 1.20x. Figures are separated from bordered prose by full-width-line share (`_MAX_PROSE_LINE_SHARE`
0.25, between 0.176 and 0.333), not text density. Extraction retires what it no longer produces only
on a complete pass. `tests/test_image_extractor.py` guards it.

## Quality gates

**I-32. An eval metric that could not be computed is a failure, never a pass.**
Requested-but-uncomputed fails; not-requested is a skip (`_check(requested=)`). No `or 0.0`, no
`or 1.0`. Inputs too: a failed search raises and leaves every retrieval rate `None`.
`tests/test_eval_gate.py` and `tests/test_eval_search_failures.py` guard it. See the `eval-integrity`
skill.

## Privacy & Local-First

**I-18. User content never reaches external telemetry, and every library's phone-home is switched off.**
Phoenix and Langfuse run locally. `import litellm` fetches a price list on every start unless
`LITELLM_LOCAL_MODEL_COST_MAP` is set; such switches are read at the library's own import, so they
are set in `app/__init__.py`. `tests/test_no_runtime_download.py` guards it.

**I-51. A macOS permission is enforced only in the signed bundle, and a missing usage string terminates rather than denies.**
`tauri dev` inherits the terminal's grant. The `.app` needs both the `Info.plist` usage string and the
entitlement, and an entitlements plist may carry no XML comment. `verify_signed.sh` checks both on
the built artefact. A feature reaching a camera, outside files or the network in a new way needs the
same pair.

## Cross-platform

**I-54. `os.kill` is not a liveness probe on Windows: every signal but a console event terminates the target.**
Use `OpenProcess` plus `GetExitCodeProcess` to ask and `signal.raise_signal` to stop; branch, do not
port. `tests/test_parent_watch.py` pins both platforms.

**I-56. Reported RAM is installed RAM minus reservations on every OS but macOS, so every site that converts it to GB rounds up.**
A 16 GiB host reported 15GB and was refused. Every reader rounds up (`memory_profile.host_ram_gb`,
the install scripts, `get-luminary.*`, `supervisor.rs`); the reported figure never exceeds installed,
so this errs safely. `test_host_support.py` and
`test_installer_models.py::test_every_ram_reader_rounds_up` guard it.

**I-59. TLS is verified against the operating system's trust store, never a bundled CA list alone.**
Behind a TLS-inspecting proxy certifi's bundle rejected the company root. `app/__init__.py` calls
`truststore.inject_into_ssl()` before any client builds a context. A remaining failure is named by
`network_errors`: only a call to the local engine may blame it.
`tests/test_network_trust_and_optional_models.py` and `test_setup_and_paths.py` guard it.

**I-60. A graphics driver on disk is not a card the model server uses; the first load decides.**
`warmup._measure_offload` reads `/api/ps` after the first local answer and
`host_support.record_offload` keeps it; a model held wholly by the processor refuses with
`gpu_unused`. The measurement narrows the device verdict, never widens it, is retaken after an
upgrade or a CUDA runner change, and `LUMINARY_HOST_SUPPORTED` outranks it.
`tests/test_gpu_offload.py` guards it.

**I-61. The frontend's requests never wait on the machine's internet connection.**
TanStack Query's default `networkMode: "online"` pauses every request once the webview reports
`offline`, though the backend is on localhost. `createQueryClient` sets `networkMode: "always"`.
`frontend/src/lib/queryClient.test.ts` guards it.

**I-62. The AppImage never bundles a library that the host's graphics drivers link against.**
Mesa, EGL and Vulkan drivers come from the host but resolve against the bundle's libraries first, so
an old bundled libwayland killed the web process on current distributions; the build machine's own
Mesa cannot show it. `scripts/desktop/prune_appimage.sh` removes host-owned libraries;
`scripts/desktop/check_appimage_host_libs.sh` fails `desktop-installers.yml` when a current distro's
driver cannot resolve, and must fail against the unpruned image. `verify_installed.sh` requires the
shell's `page loaded` line.

## Retired numbers

Kept so existing references resolve.

| # | Now |
|---|---|
| I-1 | `patterns.md`: never share an `AsyncSession` across `asyncio.gather` tasks |
| I-3 | `patterns.md`: guard Kuzu `get_next()` with `has_next()` |
| I-4 | `patterns.md`: FTS5 UNINDEXED columns are read through the content shadow table |
| I-5, I-6 | `patterns.md`: lazy imports for cycles; `get_settings` at module level |
| I-7 | `patterns.md`: persist before LLM calls in SSE generators, explicit rollback |
| I-8, I-10, I-11, I-12 | `patterns.md`, Frontend |
| I-13, I-14 | `CLAUDE.md`: `make ci` is the gate, `make smoke` the wire contract |
| I-15 | `CLAUDE.md` and a `.claude` hook: `uv` only |
| I-16 | `architecture.md`: the default path is local; cloud is opt-in |
| I-17 | merged into I-18 |
| I-19, I-20, I-21, I-22 | `concepts.md`: mastery is a stored scalar; the concept vector is derived; OKF is a projection; overrides survive re-parse |
| I-42 | `patterns.md`: a model's list field is flattened where it enters |
| I-44 | merged into I-36 |
| I-46 | merged into I-47 |
