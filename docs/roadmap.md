---
description: What is built, what is open, and what will never be built. The single place to look before proposing work. Read before starting anything not already covered by a live contract doc.
---

# Roadmap

Every other doc in `docs/` describes something that **exists**. This file is the only one that
describes work that does not, and it is the only place where status lives.

The rule that keeps it honest: **an implementation plan is deleted once its work ships.** The
code plus its live contract doc is the record; git history holds the plan. A shipped spec left
lying in `docs/` is indistinguishable from a live contract to anyone reading the tree for the
first time, and that ambiguity is more expensive than the plan is worth.

Each open item below carries evidence — a `file:line`, a gate, or a measured count. An item with
no evidence is an opinion and does not belong here.

## Shipped

The named doc is the live contract. The plan that produced the work is gone.

| Capability | Where its contract lives |
|---|---|
| Frontend lint as a CI gate, `apiClient` used everywhere | `Makefile` `ci` target, `frontend/eslint.config.js` |
| Six-layer architecture, stores, surface modes | `architecture.md` |
| The 38 hard invariants | `invariants.md` |
| Backend implementation patterns | `patterns.md` |
| Ingestion + reading (all 4 reader phases) | `universal-reader.md` |
| Hybrid retrieval: RRF, cross-encoder rerank | `retrieval-funnel.md` |
| Concepts, mastery, the studyable atom | `concepts.md`, `concepts.md` |
| Study orchestration, `POST /study/assemble` | `two-lane-model.md`, `study-launcher.md` |
| Signed macOS `.app`, notarized DMG, release flow | `desktop-bundle.md`, `releasing.md`, `releasing.md` |
| Client-side routing verification | `patterns.md` |
| Notes: CodeMirror 6 editor, wiki-links, backlinks | `architecture.md` (nav section) |
| Hub recommender + misconception lifecycle | `recommender_service.py`, `misconceptions.py` |
| Flashcard source grounding: per-card verdict, deck audit, review-time display | `invariants.md` I-34 |
| Flashcard factuality gate + recorded passage (`source_chunk_ids`) | `invariants.md` I-35 |
| Learner-facing metrics carrying sample size, definition and basis | `metrics.md` |
| An existing install carried to the model its host should run: Windows records what it pulled, a Settings card surfaces drift and switches only after the download completes | `model_router.narrowed_defaults()`, `ModelDriftNotice.tsx` |
| Content-type classification, scored against a labelled corpus rather than asserted | `services/content_classifier.py`, `tests/fixtures/content_type_labels.json` |
| Image extraction and vision enrichment, including the vector-figure fallback and its over-extraction guards | `invariants.md` I-38, `services/image_extractor.py` |
| Model footprint measured rather than estimated, three RAM bands, and a registry that refuses a model the host cannot hold | `model_registry.py`, `metrics.md` |
| Interactive work outranks background work for the Ollama slot | `services/llm_admission.py`, `tests/test_background_yields_the_slot_to_a_waiting_question.py` |
| Eval runs carry their own provenance (model, embedder, corpus fingerprint, library state) and a repair/first-pass tier | `evals/run_eval.py` `capture_environment`, `GET /evals/output-stats` |

Notes and the recommender shipped without a surviving contract doc because their behaviour is
adequately described by `architecture.md` plus the code. Their specs were deleted on
2026-08-11 under the rule above.

## Open

### 1. String-interpolated SQL

Six sites build `IN (...)` clauses by quoting values into the string rather than binding them:

- `services/vector_store.py:202,245,273`
- `services/retriever.py:189`
- `services/collection_health.py:98`
- `services/graph_view.py:60` — guarded by `.isalpha()`, so lowest risk of the six

Not currently exploitable: every interpolated id is internally generated. It is a latent
primitive that one change in id provenance turns live, and it defeats statement caching.

`graph_view.py:208,283,339,428` and `graph_tech.py:464` already bind `$name` placeholders and
are the pattern to copy. Do not "fix" those — they are already correct.

### 2. OKF is a grounding service, not yet a projection

Only the grounding half of OKF exists: `services/okf_context.py` provides `resolve_concepts`
and `build_concept_context`, consumed by `routers/qa.py`, and `concepts.md` documents that and
only that.

The unbuilt half is a **file projection** — a folder of Markdown, one file per concept plus an
index and a log, exportable and importable, so a learner model is something you can read and
edit outside the app. There is no projection, no export endpoint and no import path, and no doc
describes one: the design was removed from `docs/` on 2026-08-29 rather than left to read as a
contract. I-21 governs it if it is built (OKF is a projection, never a transport and never a
source of truth).

### 3. The `unstable` test quarantine

**28 tests across 15 files** carry `@pytest.mark.unstable` and are excluded from the default
run by `addopts`. Run them with `uv run pytest -m unstable`.

They are two different problems wearing one marker. Roughly half genuinely fail against the
current schema (the tag suite drifted). The rest pass individually but **cannot simply be
un-marked**: reclaiming them was attempted and failed — cancel-on-teardown wedges GitHub runners
into a mass error cascade, and grace-then-cancel pollutes shared Kuzu state, taking random
unrelated tests down with it.

Do not retry with timing policies. The durable fix is per-site coroutine neutralization, in the
style of the `_no_real_library_summary_generation` fixture, with opt-outs where a test genuinely
needs the background work (`test_e2e_upload` does).

Splitting the marker in two — `stale-schema` vs `leaks-tasks` — is the first step, because one
marker over two causes is why this has stalled twice.

### 4. The Hub sketch, and what is still approximate in it

Most of what issue #51 sketches is built. `frontend/src/pages/Hub.tsx` already renders the
quote, today's focus, "continue where you left off", the fading/refresher lane, the tag cloud,
active collections and a week summary, all from one fetch of `GET /home/overview`
(`routers/home.py:58`).

Both gaps against the sketch are closed: the continue lane carries notes and an open study
session, and `time_on_task` records per-activity duration for the week (`metrics.md` carries its
contract). Stored titles render through `humanizeTitle`, because two thirds of one library's
titles are the filename the document arrived as.

The page is now one 780px reading column rather than a two-column dashboard, following the
`Luminary Home v2` design handoff: a single card for the decision the hub exists for — carry on
reading, or start the review — then rows, then the week's shape two-up at the foot. The week
split is labelled bars rather than a pie, because four magnitudes compared against each other is
what a bar chart is for and a 72px pie made the small slices unreadable.

What remains is smaller and worth stating rather than assuming.

- **The ring's slices are foreground samples; `minutes_studied` beside them is session wall
  clock.** Two bases on one card. They measure different things and are labelled so, but a
  future edit that averages or sums them would produce a number meaning nothing.
- **A study interval spanning local midnight lands on the day it began**, matching
  EngagementService's approximation rather than splitting the interval.
- **`Study` cannot be deep-linked to resume a session**, so the hub no longer offers a
  continue-study lane at all: `Study.tsx` reads neither search params nor route state, and a
  session id in the URL silently starts a fresh session. Restore the lane only alongside resume.
- **"~N min left" is gone, and `readingTime.ts` with it.** It stacked a 200 wpm convention on
  section-count progress standing in for word-count progress, and a tilde plus a hover title did
  not make that legible to a reader. The hub shows the countable basis instead -- "2 of 22
  sections" -- which is the same fact in units visible on the page. Restoring an estimate means
  measuring reading speed rather than assuming one.
- **A quote carries no field of its own.** Tagging each with a subject would need a taxonomy
  applied by hand across the whole set, so the card shows author and source instead.
- **Nothing prefills a note from elsewhere in the app.** `Notes.tsx` reads neither search params
  nor route state, so "reflect on this" affordances elsewhere can only link to the page, which
  the sidebar already does.

### 5. What the reported reader and study defects left behind

All three are fixed (per-chunk citation pages, the unreachable Study landing, the search-highlight
flicker and the sheet-vs-printed page footer), as is the reader opening on its section list.
Three smaller things surfaced while fixing them and are worth stating rather than rediscovering.

- **The page box counts sheets, and it is the only surface that still does.** The footer chip,
  the contents list and every citation read the document's sheet-to-printed map, but the page
  field jumps by sheet: typing `19` on a book with twenty pages of front matter lands nowhere
  near the page printed `19`. Entering a printed number, or searching for one, has no path.
- **Opening the in-document search leaves the reader.** `InDocSearchBar` renders inside the
  section list, so Cmd+F from the Read view switches tabs to reach it — the same move the
  `?search=` deep link makes. The search belongs to the document, not to one tab.
- **The no-TOC PDF path invents headings from font size**, and on one book produced sections
  titled `27` and `265` — page numbers picked up as headings. It does not lose text, so it is a
  reading-quality defect rather than a data one.

### 6. Formats other than HTML and PDF are unmeasured

`universal-reader.md` is the contract for the reader. Region selection, the Markdown serialiser,
webview rendering and `documents.extraction_report` shipped after it was written, so it does not
yet describe them.

- `md`, `epub`, `docx` and `txt` have **no post-`body`-column documents**, so those paths are
  unmeasured rather than known good. Ingest one of each and compare stored `body` against source
  before changing anything.
- **A parent section can store its descendants' text as well as its own.** Measured: on one
  1,017-section manual the top section holds 5,063,040 characters, and 60 of 60 sampled
  sections have their opening text inside it; `SysDesign_2024_Blue` puts 55% of its document in
  one section with 26 of 40 contained. `DDIA` shows 0 of 40, so this is not every document and
  not every parser path. The reader now bounds what it fetches, so the symptom is gone, but the
  duplicated text is still stored and still costs the section it was copied from. Find the path
  that assigns a parent its children's span before changing the reader further.
- **Audio documents ingested before 0.7.5 are still unreadable.** The cause is fixed — the
  audio branch of `chunk_node` now writes one section per transcript chunk — but the fix runs at
  ingestion, so documents already in a library keep their zero sections and still return `[]`
  from `GET /sections/{id}/content`. Re-ingesting is the only way to gain them. A backfill would
  have to reconstruct sections from stored chunks, which is what I-29 forbids; if one is built
  it must read the transcript again, not reassemble it.
- `pymupdf4llm>=1.28.2` is a **core dependency with no importer** (`pyproject.toml:41`, no
  reference anywhere under `backend/`). It was added for the PDF-to-Markdown path, which is not
  built. Either build that path or drop the dependency; a shipped dependency nothing imports is
  weight in every install.
- Two known losses remain on an interactive article measured at 13 headings: the site name
  leaks as a one-word line, and a 205-character standfirst is `<h2>` in the source and therefore
  renders as a heading. Demoting it means the serialiser overruling the author's markup, which
  is a decision, not a bug fix.

### 7. Rendering reaches only the platform with a shell

`render_page` (`src-tauri/src/render.rs`) uses the webview the desktop shell embeds, so it
exists only where that shell runs — macOS today. The browser dev server, Docker and the script
installs take the static fetch, which measured full prose and headings on eight of nine test
articles; the ninth returned 0 images statically against 78 rendered.

Windows (#24) and Linux need their own shell before rendering follows. Canvas-drawn figures are
not covered on any platform: they need an element screenshot, not a DOM capture.

### 8. Two behaviours that ship without a measurement

Both are opt-out-able, both change what a user receives, and neither has a number attached.

- **The slow-host context budget.** Where the start-up probe measures local inference expensive,
  `resolve_context_budget()` narrows the synthesis budget from 1500 to 750 tokens
  (`config.py`, `QA_CONTEXT_TOKEN_BUDGET_SLOW_HOST`). The latency it buys is measured
  (~56s → ~29s prefill at 31 tok/s) and the passages it costs are measured (roughly half), but
  **the answer-quality cost is not** — the constant says so itself. It engages automatically
  above a 20s probe, so the hosts that get it are the ones least able to spare quality. Measure
  with `QA_CONTEXT_TOKEN_BUDGET=750` and a `study --generate` run before treating it as a
  shipped default rather than a rescue for hosts that are unusable without it.

- **Paraphrase recall in note search.** `make eval-notes` gates `self_recall_1`, `ghost_rate`,
  `vector_share` and `noise_rejection`, but every query it builds shares words with the note it
  should find. Nothing scores the case the semantic arm exists for: a query with no lexical
  overlap. `NOTE_SEMANTIC_MIN_SIMILARITY = 0.62` is bracketed by two measured cases (0.5004
  drop, 0.7516 keep), which justifies the threshold and does not measure the axis. `vector_share`
  catches the arm dying, not the arm getting worse.

### 9. The ingestion tests' entity extractor is a double that always raises

`NERService.extract` is `(chunks, content_type="unknown", is_technical=None)`
(`services/ner.py:458`) and `entity_extract_node` calls it with all three
(`workflows/ingestion_nodes/entity_extract.py:258`). Both test doubles stopped at the
signature it had before `is_technical`: `tests/test_e2e_upload.py:187` takes two, and
`tests/test_concurrent.py:50` takes one. **Every call raises `TypeError`**, which the node
catches as non-fatal and proceeds — so the ingestion tests pass without ever exercising
entity extraction, and each mock's carefully-built return value is dead code.

Correcting either signature is not a one-line fix, which is why this is an item rather than a
commit. Measured on one machine, minutes apart: with the broken doubles
`tests/test_e2e_upload.py` is **3 passed in 7.9s**; with the signatures corrected so
extraction actually runs, it **exceeds the 120s per-test timeout** and ingestion stalls at
`stage=indexing, progress_pct=80`. The `TypeError` is load-bearing for the suite being green.

So there are two defects stacked: the doubles have drifted, and the path they were hiding does
not complete under test. Fix the second before the first, or the gate goes red. Related to the
`unstable` quarantine (item 3) and to the leaked-task shutdown work — do not attempt it with a
timing policy, which failed before. The patch that corrects the doubles is trivial to
reconstruct from the signatures above.

### 10. `GET /documents` costs ~1.3s because its per-row counts are unindexed

The library list runs about thirteen correlated subqueries per row. Measured on a 59-document
library while three documents enriched: `GET /documents?page_size=24` takes **1.5s**, against
**0.003s** for `GET /enrichment/queue` on the same server — so this is the query, not event-loop
contention, and enrichment is not the cause.

The counts are over tables with no `document_id` index: `chunks` (75,646 rows), `sections`
(2,346), `flashcards` (826), `summaries` (452). `reading_progress`, `prediction_events` and
`learning_objectives` already have one; `enrichment_jobs` does too, and at 162 rows it is not
the cost. So the fix is an Alembic migration adding the missing indexes (I-23), not a query
rewrite — and it wants a before/after measurement on a library this size rather than a rushed one.

Bracketing what is already known: the enrichment aggregate added in `b647604` accounts for
about 0.2s of the 1.5s (the single-job version it replaced measured 1.27s on the same library,
same load). That is a real cost and worth re-measuring once the indexes exist, but it is not
what makes the page slow.

## Deferred — decided, not scheduled

Nothing currently deferred.

## Abandoned — do not restore

Each of these was built, evaluated, and removed. They are listed so the next reader proposes
something else.

- **Universe / goal-driven knowledge model** — removed 2026-06-23. Zero references survive in
  `frontend/src/pages` or `backend/app/routers`. Do not restore the Universe lens, the Goals
  **nav tab**, or the `curriculum` router/service/models. A `goals` router does survive as a data
  source for the Hub surface; that is not the abandoned feature.
- **The three-tier `public | labs | dev` vocabulary** — replaced by one env knob,
  `LUMINARY_MODE=full|public`, declared per surface in `surface-manifest.json` (v2). The labs
  drawer, tiered-install and Phase 3 specs described the superseded design and were deleted.
- **`passes=true` and a reviewer gate** — named by I-13/I-14 for months; neither ever existed in
  the repo. The gates are `make ci` and `make smoke`. A gate name with nothing behind it is worse
  than no gate, because a claim to have satisfied it cannot be checked.
- **Two Ollama services** — rejected on a single-GPU/8GB machine. See I-31: enrichment cost is
  call count, not concurrency, so the lever is fewer calls, never more parallelism.

## Adding to this file

An entry is warranted when work is **decided but not done**, or **rejected and likely to be
re-proposed**. A bug is an issue, not a roadmap item. When an open item ships, delete its entry
and add a row to Shipped naming the doc that now carries the contract.
