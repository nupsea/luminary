---
description: What is built, the features coming next, and what will never be built. The single place to look before proposing work. Defects live in the issue tracker, not here.
---

# Roadmap

Every other doc in `docs/` describes something that **exists**. This file is the only one that
describes work that does not, and it is the only place where status lives.

The rule that keeps it honest: **an implementation plan is deleted once its work ships.** The
code plus its live contract doc is the record; git history holds the plan. A shipped spec left
lying in `docs/` is indistinguishable from a live contract to anyone reading the tree for the
first time, and that ambiguity is more expensive than the plan is worth.

**Defects are issues, not roadmap items.** This file had drifted into a defect log against its
own rule; on 2026-08-29 the nine that were left moved to the tracker
([#95](https://github.com/nupsea/luminary/issues/95)–[#103](https://github.com/nupsea/luminary/issues/103)),
along with the evidence each carried. The test-suite quarantine lives in
[#50](https://github.com/nupsea/luminary/issues/50).

What belongs here is a **feature large enough to change what Luminary is for** — something a
user would notice arriving, that needs a decision before it needs code. Each entry says what
already exists, because the hard part is usually a constraint rather than the build.

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

## Roadmap

Four features, in the order they unblock each other. Each says what exists today, because most
of them are half-seamed already and the work is smaller than it looks from the outside.

### 1. Anki import, and a real round-trip

**Export already ships**: `export_service.py` writes a `.apkg` through genanki, one card per
`FlashcardModel` in a collection's deck (`GET /collections/{id}/export?format=anki`). There is
no import path at all.

The point is not symmetry for its own sake — it is that a learner arrives with a deck they have
already invested in, and today Luminary cannot read it. Import is the adoption path.

The hard part is not the file format. A Luminary card carries `source_chunk_ids` and a
per-card grounding verdict (I-34, I-35); an imported card has no passage in the library to
point at. So importing has to answer what grounding means for a card whose source is elsewhere
— shown as ungrounded, allowed to bind to a document later, or held in a separate lane. Decide
that before writing a parser, or the invariant quietly stops meaning anything.

FSRS state is the other question: an Anki deck carries SM-2 scheduling, and `fsrs` v6 state is
not the same shape. Importing intervals naively would produce a schedule that looks continuous
and is not.

### 2. Sync the library through a file-sync service

iCloud Drive, OneDrive, Dropbox, Google Drive — the services people already pay for, rather
than a server Luminary would have to run. This keeps the local-first promise: no account, no
backend, no data leaving except into storage the user already controls.

**The live stores cannot be the thing that syncs.** SQLite (with WAL), LanceDB and Kuzu are all
mid-write-sensitive; a sync daemon copying a `-wal` or a Kuzu directory mid-write produces a
corrupt library on the other machine, and Kuzu holds a lock besides. So the design is a
snapshot/restore format that syncs, with the live stores rebuilt from it — never the stores
themselves in a synced folder.

That makes this the same work as the **OKF file projection**: a folder of Markdown, one file
per concept plus an index and a log, that a user can read and edit outside the app. Only the
grounding half of OKF exists today (`services/okf_context.py`, documented in `concepts.md`);
the projection does not. I-21 governs it — OKF is a projection, never a transport and never a
source of truth — which is exactly the property a sync format needs.

Conflict resolution is the open question, and it is the reason this is a feature rather than a
script: two machines that both studied offline have divergent FSRS state, and last-writer-wins
would silently discard a review session.

### 3. A mobile client for capture and review

Note taking and flashcard review — the two things you do away from a desk. Reading and ingest
stay on the machine that has the models.

The backend is already HTTP, so the surface exists. Two things do not. **There is no
authentication** — Luminary is single-user and local by design, and every store is a local file
opened by one process; a phone reaching a laptop backend needs an answer to who is asking.
And a phone that only works while the laptop is awake is not much of a client, so the honest
version needs local storage on the device and a sync path back — which is feature 2, and why
it comes second.

`surface-manifest.json` already declares each surface's mode, so a mobile build can be a
third mode rather than a fork.

### 4. Multi-language and cross-language support

Two separate pieces of work that get confused with each other.

**Interface localisation** is seamed but unbuilt: every surface in `surface-manifest.json`
carries `labels: {"en": ...}`, so the shape is there and nothing else is.

**Cross-language retrieval** is the harder and more valuable one — asking a question in English
about a German paper, or vice versa. The blocker is concrete: embeddings are
`BAAI/bge-small-en-v1.5`, 384-dim and English-only, and every stored chunk, note, image and
concept vector lives in that one space. Moving to a multilingual embedder changes the space, so
**every vector in every library has to be regenerated** — which is a migration with a re-embed
cost proportional to the library, not a config change. GLiNER is already multilingual
(`gliner_multi_pii-v1`), so entity extraction would survive the move; retrieval would not.

Worth measuring before committing: how far the current stack degrades on non-English text, so
the re-embed is justified by a number rather than by an assumption.

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

An entry is warranted when a **feature** is decided but not done, or rejected and likely to be
re-proposed. When one ships, delete its entry and add a row to Shipped naming the doc that now
carries the contract.

**A bug is an issue, not a roadmap item** — that rule was already here, and this file drifted
from it anyway. The tell is an entry that names a `file:line` and a symptom rather than a
capability: that is a defect with good evidence, and the evidence belongs in the tracker where
someone can close it. If an entry could be titled "X is broken", it is an issue.
