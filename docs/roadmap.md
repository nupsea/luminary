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
| The 39 hard invariants | `invariants.md` |
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
| Documents carry three facets (form, domain, register) behind one derived profile, written at ingest and readable per document | `types.py` `DocumentProfile`, `workflows/ingestion_nodes/parse.py` `_persist_classification` |

Notes and the recommender shipped without a surviving contract doc because their behaviour is
adequately described by `architecture.md` plus the code. Their specs were deleted on
2026-08-11 under the rule above.

## Roadmap

**1.0.0 is a major public release, reached through a ladder of minor versions.** Each rung carries
one theme, one exit gate that can come out red, and leaves the app whole if the rung after it never
ships. Patch numbers are release plumbing here — 0.8.0 to 0.8.28 took one day — so the minor is the
planning unit.

Rung numbers are ordering, not commitments. Several will split once scoped.

The ladder was re-cut on 2026-09-05. The four rungs that lead are experience rungs, and the integrity
rungs that used to be 0.10.0–0.12.0 sit behind them. The whole cost of that trade is that four
feature rungs land on a suite with a live quarantine, so **a rung ships its smoke scripts with its
endpoints (I-14) and adds nothing to the quarantine**. If the quarantine grows once, 0.14.0 moves
back up the ladder.

| Rung | Theme | Exit gate |
|---|---|---|
| 0.10.0 | Smart Hybrid, and the privacy receipt | Time to first token measured on both arms from a cold install and reported as a pair; a test proves that only the question and its packed passages leave the machine |
| 0.11.0 | The docked reader | A citation survives selection → note → resolution back to the exact locus for page, video, code and web; no modal opens from the reader |
| 0.12.0 | The Brief | Every claim in a Brief resolves to a chunk of that document, measured on the golden corpus against a floor that can come out red |
| 0.13.0 | Capture | Three source types round-trip from the browser to a readable document; an unpaired origin is refused |
| 0.14.0 | Gates you can believe | `make ci` and `make smoke` both green, nothing quarantined to keep them so |
| 0.15.0 | Stores that agree, ingest you can measure | A reprocess killed midway leaves no divergence between stores; every ingest path reports a measured fidelity number |
| 0.16.0 | Windows | First-run setup completes on a machine that has never seen Luminary |
| 0.17.0 | The re-embed rail | A full re-embed of a real library runs to completion, survives being killed, and resumes |
| 1.0.0 | The public release | Every rung's exit gate green together, on one build |

**1.0.0 itself carries no new features.** Work not on a rung above is 1.1, not 1.0.

Startup only ever runs `upgrade head`, so a newer library cannot be opened by an older build
(`releasing.md`). Every migration is a one-way door, which is why what remains of the document-model
work and the re-embed rail both stay inside 0.x.

### 1. Smart Hybrid, and the privacy receipt — 0.10.0

**The routing already exists and nobody is ever offered it.** `settings_service.get_effective_routing`
sends interactive work to the cloud and background work to Ollama under `llm_mode="hybrid"`; the
default is `private` and no first-run question changes it. A stranger evaluating Luminary meets a
40–90s first answer, which is a verdict rather than a wait.

What ships is the offer, the perceived latency, and the receipt.

- First run asks one question — fast or private — each stated with its own measured latency, key
  pasted inline. **No key still means a fully working local app.** I-16 is what makes hybrid an offer
  rather than a default, and it is not negotiable by a growth argument.
- Retrieval renders before generation: source chips paint when retrieval returns, the answer streams
  after. On the local arm this is the difference between "thinking" and "dead".
- Every answer carries engine, latency, cost, and what left the machine — N passages, M tokens, which
  provider. The routing table is a Settings surface, not a sentence in a doc.

**Only synthesis is routable.** Embedding is not: one 384-dim space holds every stored vector, so a
hosted embedder is a migration and never a setting (I-9). Retrieval, transcription, entity extraction
and the learner record stay local in every mode, which is what makes the privacy claim checkable
rather than promised.

**What a number from this rung may be compared against.** The retrieval arm defaults `--rerank` to the
backend's `rerank_enabled` and exits rather than guessing when it cannot read it (`shipped_rerank`,
`run_eval.py`), so the arm measures the funnel a user gets — `--no-rerank` is the ablation and says so.
Retrieval baselines recorded before 2026-08-26 are the unreranked funnel and are not comparable to
anything this rung produces.

**Exit gate, half taken.** `make measure-ttft` reads the figure each answer's receipt reports rather
than timing from outside, so a quoted number is the one a user sees. Measured 2026-09-06, local arm,
`ollama/qwen3.5:4b`, 5 runs scoped to one document, 5–6 passages, default 1500-token budget:

| | |
|---|---|
| first visible content (source chips) | median 1.85s |
| first token | median 3.22s (1.89–3.37) |
| complete answer | 18.9–40.7s |

**The pair is not complete**: the cloud arm needs a provider key and has not been measured, and a
mean across arms would describe no system that exists — `measure_ttft.py` refuses to compute one.

**This corrects a premise stated earlier in this plan.** "A stranger meets a 40–90s first answer"
conflated time-to-first-token with total answer time. On a host the probe does not call slow, first
token is ~3s; it is the *complete* answer that takes 19–41s. That is what retrieval-first rendering
is worth: source chips at 1.85s in place of a blank panel for the whole of it. A genuinely slow host
is still the case the hybrid offer exists for, and it remains unmeasured here.

**The number that must not be bought.** `resolve_context_budget()` already narrows the synthesis budget
from 1500 to 750 tokens on a slow host with the answer-quality cost unmeasured (#100). A second latency
win taken out of content is the failure this rung is most likely to produce.

### 2. The docked reader — 0.11.0

**Three modals cover the text the reader is reading.** `QuickNoteComposer` is a dialog, `Chat` is a
global slide-over owned by `App.tsx`, `FeynmanDialog` is a third dialog. The resizable right panel
that would hold all three already exists and shows only summaries and chapter goals.

The panel becomes the assistant: `Notes · Key Points · Detailed · Glossary · References · Ask AI ·
Practice`. Selection actions dock into it instead of opening anything, and the citation travels with
the action. `SelectionActionBar` already emits `onAddToNote`, `onAskInChat`, `onExplain` and `onClip`
with a `SourceRef` — the wiring exists and lands in modals.

The centre pane re-skins by type while the docked workflows stay constant. **The citation format is
the part that is per-type and load-bearing**: `p.151 · §5.2`, `VIDEO 14:22`, `raft.go · L214`,
`domain · ¶4`. A clip from a transcript carries a seekable timestamp or the note has lost the thing
that made it checkable.

**The one real refactor is `Chat.tsx`** — 1518 lines, a page-level default export with no props. A
`ChatConversation` component has to come out of it reading scope from the store rather than the render
closure; the comment at its send handler records the shipped bug that happens otherwise (a library
question scoped to a PDF 40 seconds into ingestion).

The same rung cuts the public nav to five rail items — Home, Library, Notes, Study, Progress. Ask
lives where it has a scope, Map stays in `full`, and `blog` moves `full` → `public` because the output
is what gets shared. All four are `surface-manifest.json` edits.

**A rate of 1.0000 on the citation round-trip is a rubber stamp unless a deliberately unresolvable ref
is in the same test and fails.** See `.claude/rules/common/verify-before-reporting.md`.

### 3. The Brief — 0.12.0

Ingest finishes and the document has already said what it contains: a one-sentence thesis, five claims
it makes with a marker-resolved verbatim quote and locus each, three questions it answers, and what it
does not cover. It renders in the existing Key Points tab and on the library card — no new surface.

**The claims are safe by construction and the questions are not.** A claim's quote comes from
`_resolve_marker_citations`, so it is verbatim because the excerpt is sliced from the chunk the marker
names (I-33). The questions are the feature described in **#66**: `SuggestionService.get_grounding_passages`
prefers `SectionSummaryModel.content`, so questions are generated from a paraphrase, presuppose framings
the document never makes, and the answer that follows renders with a confidence chip and five source
chips while being ungrounded. Moving that to first-run puts it where it does the most damage.

Three things have to be true before the questions ship: generation reads chunk text, each question is
validated by running retrieval and dropped when nothing scores, and the general-knowledge fallback in
`QA_FACTUAL_SYSTEM_PROMPT` is suppressed for a question the product itself suggested.

**"What it does not cover" is a claim about absence**, so it is only worth shipping if it can be wrong:
test it against questions the document demonstrably does answer.

Paired with the Brief, the first-run reward stops being a flashcard. `feynman_service` already grades an
explanation against the chapter and returns a critique naming the page; that is the payoff, and the cards
come after it as the consequence of being measured.

### 4. Capture — 0.13.0

**A library stays empty when filling it means opening the app and finding the file.** This is not the
mobile rung and is much cheaper than it: the backend is already HTTP on :7820, so an extension needs a
POST rather than an architecture. One click for a page, a PDF, a YouTube video or a selection with its
source; a watch-folder for the desktop app; Markdown export shaped for Obsidian and a Zotero read path.

**Pairing ships with it, not after it.** The backend is unauthenticated on localhost and CSRF is
deliberately open, so any page in any tab can already POST to :7820 — an extension turns a latent hole
into a documented invitation. The gate is that an unpaired origin is refused, proven by a test that
fails when pairing is removed.

### 5. Gates you can believe — 0.14.0

`make ci` and `make smoke` green together with nothing quarantined to keep them so: 22 `pytest.mark.unstable`
markers across 14 files today (#50). Local green is necessary and not sufficient — GLiNER memory pressure
has produced GitHub-only failures no local run reproduces.

This rung exists to shrink as the ladder runs. It grows only if a rung above it breaks the no-new-quarantine
rule, and that is the signal to move it back up.

### 6. Stores that agree, ingest you can measure — 0.15.0

A failed graph write is lost and SQLite and Kuzu diverge with nothing reconciling them (#65). Entity ingest
samples 2.4% of a long book and reindex disagrees with ingest (#63). The md/epub/docx/txt paths are
unmeasured and a parent section can store its descendants' text (#97).

**The last of the document-model work belongs here.** `form`, `domain` and `register` are written at ingest
by `_persist_classification` and `DocumentProfile` owns the policy, so what remains is retiring the legacy
`content_type` projection and `is_technical` now that 0.9.0 has shipped without them being the source of
truth. It is a migration, and migrations get more expensive with every user.

### 7. Windows — 0.16.0

A public 1.0 that runs on one operating system is a beta with a version number. The macOS bundle is signed
and notarized; Windows is #24. The gate is a first run that completes with no terminal on a machine that has
never seen Luminary.

### 8. The re-embed rail — 0.17.0

**Build the migration, not the model swap.** Moving to a multilingual embedder regenerates every vector in
every library, and 0.x is the last point at which the compatibility promise is weak enough to absorb that —
but the argument is about the machinery, not about the model. A resumable, restartable re-embed path plus
the snapshot/restore format is the same work sync needs and the same work the OKF projection is (I-21).

Proven against the current 384-dim embedder, where a wrong answer costs nothing. The multilingual swap then
becomes a 1.x decision backed by the measurement nobody has taken: how far the current stack actually
degrades on non-English text.

## After 1.0

Each of these needs a decision before it needs code, and none of them blocks a launch.

**Anki import.** Export already ships — `export_service.py` writes a `.apkg` through genanki for a
collection's deck. There is no import path. The hard part is not the file format: a Luminary card carries
`source_chunk_ids` and a per-card grounding verdict (I-34, I-35), and an imported card has no passage in the
library to point at. Decide what grounding means for a card whose source is elsewhere — shown as ungrounded,
bindable to a document later, or held in a separate lane — before writing a parser, or the invariant quietly
stops meaning anything. FSRS state is the second question: an Anki deck carries SM-2 scheduling, and `fsrs`
v6 state is not the same shape, so importing intervals naively produces a schedule that looks continuous and
is not.

**Sync through a file-sync service.** iCloud Drive, OneDrive, Dropbox, Google Drive — storage the user already
controls, so no account and no server. **The live stores cannot be the thing that syncs**: SQLite with WAL,
LanceDB and Kuzu are all mid-write-sensitive, and a daemon copying a `-wal` or a Kuzu directory mid-write
produces a corrupt library on the other machine. What syncs is the snapshot format from 0.17.0, with the live
stores rebuilt from it. Conflict resolution is the open question and the reason this is a feature rather than
a script: two machines that both studied offline have divergent FSRS state, and last-writer-wins silently
discards a review session.

**A mobile client for capture and review.** Note taking and flashcard review — the two things done away from
a desk. Reading and ingest stay on the machine with the models. The backend is already HTTP, so the surface
exists; **there is no authentication**, and a phone reaching a laptop needs an answer to who is asking. A
phone that only works while the laptop is awake is not a client, so the honest version needs on-device storage
and a sync path, which is the entry above. `surface-manifest.json` already declares each surface's mode, so a
mobile build is a third mode rather than a fork.

**The multilingual embedder swap.** Embeddings are `BAAI/bge-small-en-v1.5`, 384-dim and English-only, and
every stored chunk, note, image and concept vector lives in that space. GLiNER is already multilingual
(`gliner_multi_pii-v1`), so entity extraction survives the move and retrieval does not. Interface localisation
is separate and seamed but unbuilt: every surface in `surface-manifest.json` carries `labels: {"en": ...}`.

## Deferred — decided, not scheduled

- **A serving width of 4, for a machine that asks for it.** Every install path sizes
  `OLLAMA_NUM_PARALLEL` from physical RAM and caps the automatic value at 2 (I-31): `performance`
  is reachable from RAM now, so a 4 keyed to that profile would hand every 32GB machine a width
  the measured table never reached — it stops at two callers, 97.7 tok/s. Four is still reachable
  by writing `OLLAMA_NUM_PARALLEL=4` into `.env`. What does not exist is the path that tells a
  profile a human chose from one sized from RAM: `memory_profile.profile_is_explicit()` answers it
  for the backend and no installer reads it, so an explicit `LUMINARY_PROFILE=performance` cannot
  re-enable 4 on its own. Worth building only together with a measurement at four slots, which
  nobody has taken.

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
