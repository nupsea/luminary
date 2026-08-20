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
| The 35 hard invariants | `invariants.md` |
| Backend implementation patterns | `patterns.md` |
| Ingestion + reading (all 4 reader phases) | `universal-reader.md` |
| Hybrid retrieval: RRF, cross-encoder rerank | `retrieval-funnel.md` |
| Concepts, mastery, the studyable atom | `concepts.md`, `concept-model-design.md` |
| Study orchestration, `POST /study/assemble` | `two-lane-model.md`, `study-launcher.md` |
| Signed macOS `.app`, notarized DMG, release flow | `desktop-bundle.md`, `releasing.md`, `release-credentials.md` |
| Client-side routing verification | `router-verification.md` |
| Notes: CodeMirror 6 editor, wiki-links, backlinks | `architecture.md` (nav section) |
| Hub recommender + misconception lifecycle | `recommender_service.py`, `misconceptions.py` |
| Flashcard source grounding: per-card verdict, deck audit, review-time display | `invariants.md` I-34 |
| Flashcard factuality gate + recorded passage (`source_chunk_ids`) | `invariants.md` I-35 |
| Learner-facing metrics carrying sample size, definition and basis | `metrics.md` |

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

`okf.md` describes a folder of Markdown files — one per concept, plus `index.md` and `log.md` —
as an export/import/grounding layer. Only the grounding half exists: `services/okf_context.py`
provides `resolve_concepts` and `build_concept_context`, consumed by `routers/qa.py`. There is
no file projection, no export endpoint, and no import path.

I-21 already governs the unbuilt half (OKF is a projection, never a transport and never a source
of truth), so build it against that invariant when it is built. `okf.md` is marked accordingly.

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

### 4. Model footprint, scheduling, substitutability, and the eval baseline that gates them

A 0.5.0 user reported ~16GB resident and a crash ingesting a PDF. `spawn_ollama` in
`src-tauri/src/supervisor.rs` sets `OLLAMA_KEEP_ALIVE=30m` but never
`OLLAMA_MAX_LOADED_MODELS`, whose Ollama default is 3, so chat and vision runners co-reside
for half an hour. `scripts/install.sh:198` and `scripts/bootstrap.sh:257` both cap it; the
DMG path does not.

Two further problems share the fix. Deferred summaries and enrichment issue LLM calls into
the slots an interactive Ask needs, with no scheduling priority between them. And model
substitution (#48) does not move eval numbers, because prompts, parsers and budgets are
sized for llama3.2 and no metric distinguishes a model that emits clean JSON from one whose
output is repaired — there are two tolerant parsers and nothing counts a repair.

A fourth problem gates all three. Three independent eval audits (2026-08-14) found that no
number in the suite survives being compared across a change: a run records nothing about the
embedder, model or library state that produced it, one generation run cannot resolve a change
below ~0.10, `run_summary_eval.py:38` judges summaries against 8,000 raw bytes, and every gated
arm pins `document_id` so cross-document routing is unmeasured.

Plan, six stages: `model-and-eval-plan.md`. Delete it when the last stage ships.

### 5. An existing install is never moved to the model its host should run

Changing the default model moves new installs only. There is no path that carries an existing
one across, and for two of the three install routes the result is that chat stops answering.

`scripts/install.sh` before 2026-08-19 pulled `llama3.2` and never wrote
`LITELLM_DEFAULT_MODEL`, and the desktop app writes no `.env` at all —
`supervisor.rs:298` only reads `OLLAMA_NUM_PARALLEL` and `OLLAMA_MAX_LOADED_MODELS` back out.
Both therefore resolve the host-aware default, which is not the model on disk:
`warmup.py:125` reports `chat_model: missing`, and `components.py:285` lists catalogue entries
only, so the setup screen offers a 3.21GB download and never mentions the working 2.88GB model
the user already has. `bootstrap.sh` wrote the pin, so those installs keep working and are the
only ones that do.

The primitives exist. `POST /setup/components/model:<ref>/install` installs any registry entry
with streamed progress, `PATCH /settings/llm {local_chat_model}` switches, and `settings` is a
key/value table (`models.py:439`), so remembering a dismissal needs no migration. What is
missing is the comparison — what is in play against what this host would pick, and whether that
is installed — and one surface for it.

Two constraints decide the design:

- **Frame it as fit, never quality.** `TEXT_PREFERENCE` is ranked on single runs and says so;
  it ranks a default and does not gate a swap. "This machine can hold a larger model" is
  measured. "This model is better" is not, and claiming it is the failure
  `.claude/rules/common/product-integrity.md` exists to prevent.
- **The download completes before the pin flips.** Switching to a model that is not on disk is
  what the silent host-aware upgrade did before `_named_by_a_human` gated it, and it fails at
  the user's first question rather than at the point of choosing.

Removing the superseded model is a separate step, default off, and confirmed.

### 6. The Hub sketch, and what is still approximate in it

Most of what issue #51 sketches is built. `frontend/src/pages/Hub.tsx` already renders the
quote, today's focus, "continue where you left off", the fading/refresher lane, the tag cloud,
active collections and a week summary, all from one fetch of `GET /home/overview`
(`routers/home.py:58`).

Both gaps against the sketch are closed: the continue lane carries notes and an open study
session, and `time_on_task` records per-activity duration for the weekly ring (`metrics.md`
carries its contract). The hub opens on a choice between flow and recall — a resume card beside
the day's review — and stored titles are rendered through `humanizeTitle`, because two thirds of
one library's titles are the filename the document arrived as.

What remains is smaller and worth stating rather than assuming.

- **The ring's slices are foreground samples; `minutes_studied` beside them is session wall
  clock.** Two bases on one card. They measure different things and are labelled so, but a
  future edit that averages or sums them would produce a number meaning nothing.
- **A study interval spanning local midnight lands on the day it began**, matching
  EngagementService's approximation rather than splitting the interval.
- **`Study` cannot be deep-linked to resume a session.** The hub's study row routes to the page
  because `Study.tsx` reads neither search params nor route state, so a session id in the URL
  would silently start a fresh session.
- **"~N min left" stacks two approximations.** Reading speed is a convention (200 wpm, named in
  `readingTime.ts`), and reading progress counts sections rather than words, so the words
  remaining assume sections of roughly equal length. It is labelled with a tilde and carries its
  basis on hover; it is not a measurement and must not be promoted to one.
- **A quote carries no field of its own.** Tagging each with a subject would need a taxonomy
  applied by hand across the whole set, so the card shows author and source instead.
- **Nothing prefills a note from elsewhere in the app.** `Notes.tsx` reads neither search params
  nor route state, so "reflect on this" affordances elsewhere can only link to the page, which
  the sidebar already does.

### 7. What the reported reader and study defects left behind

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

### 8. Formats other than HTML and PDF are unmeasured

`universal-reader.md` is the contract for the reader. Region selection, the Markdown serialiser,
webview rendering and `documents.extraction_report` shipped after it was written, so it does not
yet describe them.

- `md`, `epub`, `docx` and `txt` have **no post-`body`-column documents**, so those paths are
  unmeasured rather than known good. Ingest one of each and compare stored `body` against source
  before changing anything.
- **Audio documents are retrievable and unreadable.** Measured on the four `wav` documents in
  one library: each is `stage=complete` with its whole transcript in chunks (2,948 to 15,301
  words, 28,991 in total), and each has **zero sections**, so `GET /sections/{id}/content`
  returns `[]` and the reader shows "No content available". The orphan-chunk fallback in
  `sections.py` cannot cover this: it fires only when sections exist but are empty
  (`all(not r.content for r in result) and result`), and here `result` is itself empty. The
  transcript is chunked without ever being sectioned, so retrieval finds it and the reader
  cannot show it.
- `pymupdf4llm>=1.28.2` is a **core dependency with no importer** (`pyproject.toml:41`, no
  reference anywhere under `backend/`). It was added for the PDF-to-Markdown path, which is not
  built. Either build that path or drop the dependency; a shipped dependency nothing imports is
  weight in every install.
- Two known losses remain on an interactive article measured at 13 headings: the site name
  leaks as a one-word line, and a 205-character standfirst is `<h2>` in the source and therefore
  renders as a heading. Demoting it means the serialiser overruling the author's markup, which
  is a decision, not a bug fix.

### 9. Rendering reaches only the platform with a shell

`render_page` (`src-tauri/src/render.rs`) uses the webview the desktop shell embeds, so it
exists only where that shell runs — macOS today. The browser dev server, Docker and the script
installs take the static fetch, which measured full prose and headings on eight of nine test
articles; the ninth returned 0 images statically against 78 rendered.

Windows (#24) and Linux need their own shell before rendering follows. Canvas-drawn figures are
not covered on any platform: they need an element screenshot, not a DOM capture.

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
