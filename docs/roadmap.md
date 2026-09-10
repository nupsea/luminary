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
| The 50 hard invariants | `invariants.md` |
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
| A citation lands on its passage -- marked, centred and held there -- in prose, transcripts and as an overlay on the PDF page itself | `invariants.md` I-41, `frontend/src/lib/citation/`, `make verify-citation` |

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
| 0.11.0 | The docked reader | A passage captured in the reader resolves back to its locus for page, video and web; no modal opens from the reader |
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

**Exit gate, both arms.** `make measure-ttft` reads the figure each answer's receipt reports rather
than timing from outside, so a quoted number is the one a user sees. Measured 2026-09-10, the two arms
back to back on one machine, same document, same question, 20 passages each, default 1500-token
budget — an earlier local-only run on 2026-09-06 scoped 5-6 passages and is **not** comparable to
these:

| | local (`ollama/qwen3.5:4b`) | cloud (`openai/gpt-5.6-sol`) |
|---|---|---|
| first token, median | 3.14s | 2.30s |
| first token, range | 2.21-3.54s | 1.62-2.90s |
| complete answer | 13.8-36.6s | 5.7-10.8s |

Five runs per arm, all five producing a token. `measure_ttft.py` still refuses to average across
arms: a single mean here would describe no system that exists.

**The pair says something the local number alone did not.** Time to first token barely moves —
0.84s of median between the arms — while the complete answer moves by a factor of two to three.
Both arms retrieve locally, and retrieval is most of the wait before the first token, so the cloud
buys the *finish*, not the start. A release note quoting the cloud arm as "faster to first token"
would be quoting noise. The slowest run on each arm was its first, on both arms, which is warm-up
and not a difference between them.

**This corrects a premise stated earlier in this plan.** "A stranger meets a 40–90s first answer"
conflated time-to-first-token with total answer time. On a host the probe does not call slow, first
token is ~3s; it is the *complete* answer that takes 19–41s. That is what retrieval-first rendering
is worth: source chips at 1.85s in place of a blank panel for the whole of it. A genuinely slow host
is still the case the hybrid offer exists for, and it remains unmeasured here.

**The number that must not be bought.** `resolve_context_budget()` already narrows the synthesis budget
from 1500 to 750 tokens on a slow host with the answer-quality cost unmeasured (#100). A second latency
win taken out of content is the failure this rung is most likely to produce.

**The offer now has a door for a library that already exists.** `EngineChoice`
was mounted only by `FirstRunGuide`, which `Hub.tsx` renders only from `HubEmpty`:
no today action, no recent items, no active collections, nothing to continue
reading, nothing fading. An upgrade meets none of those conditions, so every
library carrying documents from before this rung kept the `private` default
without being asked and met the complete-answer time the rung exists to explain.
`EngineOffer` is the same question on the Hub's non-empty branch. It renders
`EngineChoice` rather than restating it -- two wordings about what leaves the
machine is two things to keep true (I-16).

The condition is the row, not the value. `settings` on the install this was found
on holds no `llm_mode` row at all, and `private` reads the same whether it was
chosen or defaulted, so `get_llm_settings` reports `mode_chosen` from whether the
row exists (`test_a_library_that_was_never_asked_reports_no_choice`). Waving the
offer away is stored separately as `llm_offer_dismissed`: declining to decide is
not a decision, and a notice that returns on every launch is a nag.

**The offer, once accepted, used to produce an answer that could not resolve.**
`get_effective_routing` returns `f"{provider}/{cloud_model}"` from two settings
written independently, and the engine question sends a provider and no model --
so picking Anthropic, the question's own default, left `gpt-4o-mini` in place and
routed `anthropic/gpt-4o-mini`. A provider *change* now carries that provider's
default model, while a model picked for the provider being kept survives. That is
I-53.

**Where the key lands is now read from the machine rather than promised.** The
key panel said "stored in your OS keychain, never in the library" everywhere,
including the installs that have no keyring -- Docker, headless Linux -- where
the write path already falls back to a plaintext row in the library database.
`keyring_available` reports which of the two will happen, and the sentence
follows it. README carries the same split per install path.

### 2. The docked reader — 0.11.0

**The reader's work used to open over the text it was about.** The note composer was a dialog, the
conversation a global slide-over owned by `App.tsx`, an explanation a sheet with a backdrop, and the
flashcard generator and the Feynman session two more dialogs. The resizable right panel that would
hold all of them already existed and showed only summaries and chapter goals.

The panel becomes the assistant: `Insights · Ask AI · Notes · Practice`, with `Explain` joining it
while there is an explanation to read. Selection actions dock into it instead of opening anything,
and the citation travels with the action.

**The selection bar ends up narrower than this rung planned.** It offered Note, Flashcard and Clip
alongside Explain, Ask and the four highlight swatches, and each of the three was a second door to a
face now docked two inches away: a note is written in the Notes face, a deck is scoped in the
Practice face, and a passage is kept with a swatch. Removing them leaves highlighting as the whole of
passage capture, which costs the one thing Clip did that a swatch does not — a clip became a *note*,
so it was searchable, taggable and in the note graph, and it recorded the passage's `chunk_id` where
a highlight resolves to a section or a page. That is what the exit gate above now says.

The centre pane re-skins by type while the docked workflows stay constant. **The citation format is
the part that is per-type and load-bearing**: `p.151 · §5.2`, `VIDEO 14:22`, `raft.go · L214`,
`domain · ¶4`. A clip from a transcript carries a seekable timestamp or the note has lost the thing
that made it checkable.

**The conversation is a component.** `ChatConversation` holds the thread, the composer and the session
list; `variant="docked"` drops the session list, the back button and the `?q=` prefill, and `Chat.tsx`
is now the route around it. Scope has come from the store rather than the render closure since
`957b5be` (a library question scoped to a PDF 40 seconds into ingestion).

**A conversation belongs to the surface holding it.** `chatThreads` is keyed — `page` for Ask, and
`doc:<id>` for a conversation docked in a reader — because one global thread meant the dock would
re-scope the Ask page, which is the defect `957b5be` fixed once already. A docked conversation is
pinned to its document and offers no scope picker. Preloaded questions are addressed the same way
(`preloadIsFor`), so an `autoSubmit` question cannot send itself into the wrong conversation.

`make verify-dock` measures what no unit test can see, because all of it is about mounted components
sharing one store: asking about a passage keeps the reader on the passage, the reader's conversation
leaves the Ask page's thread and scope untouched, and taking a note opens nothing over the text.
Each of those is fired, not assumed. Pointing the dock at the page thread turns four checks red;
rendering the composer as a sheet again turns three red — `1 dialogs`, `0 composers`, and the second
selection cannot be made at all, because the sheet is over the transcript; dropping `captureKey`
turns the append check red at `3 -> 3 quoted lines`.

**A citation points in the terms its source has.** `lib/citation/locus` picks one locus per source —
a moment for a recording, a page for a paginated document, otherwise the section — and returns null
when the source has none, which is what stops a chip claiming "p.0". Its tests carry a deliberately
unresolvable ref that must format to nothing.

The moment is new data. Transcription groups Whisper segments into ~60s windows carrying both bounds
and the write dropped them, so `ChunkItem.start_time` was served hardcoded null for every document
(`routers/documents.py`) and the transcript view's timestamp span never rendered. `chunks.start_time`
and `end_time` now persist it, and `ChunkLocation` is a NamedTuple so the next field added to a
citation's location cannot silently shift the three call sites that unpack it.
**Recordings ingested before this carry no timings; only a re-ingest fills them.**

**`raft.go · L214` has no substrate.** The code chunker stores its start line in `chunks.page_number`
(`chunk.py`) and sets nothing else — no `code_language`, no flag — so a citation cannot tell a line
from a page, and `end_line` is computed and discarded. The locus module deliberately has no `line`
kind until something can supply one.

**The composer is a component too.** `NoteComposer` holds the capture; `variant="sheet"` is what a
page with no room beside it opens — `QuickNoteComposer` is now that wrapper, and `pages/Notes.tsx`
still uses it — while `variant="docked"` is the reader's third panel face. A docked composer outlives
the capture that opened it, so a second selection appends into the draft (`appendCapture`) instead of
being dropped; a modal could only ever hold a first. When nothing is being captured the tab lists
this document's notes, and the header's note count opens that list rather than leaving for `/notes`.
Collapsing the panel now hides it rather than unmounting it: a layout change may not cost a streaming
answer or an unsaved draft.

**A note opened from a document is edited beside it.** The panel's list opens a note in the docked
composer — the full note page is where *expanding* one goes, not where opening one goes. Editing an
existing note there binds the autosave to that note; a note that already existed is never discarded
for being emptied, which is only ever a new draft's fate.

Expanding carries the way back: the note page's `from` names `/library?doc=…&note=…` rather than a
history step, so Back returns to the reader with the note open in its panel again. A `from` with a
query is a place, not a step — `goBack()` alone lands on the bare document.

**A composer with no preview renders as it writes.** The panel is a third of the width, so nothing
can sit beside the editor. `liveMarkdown` hides each inline marker on every line but the one the
cursor is on, and draws blocks — fenced code, tables, an image on its own, `$$` math — with
`MarkdownRenderer`, the component the preview uses, so the editor and the preview cannot disagree
about what a note looks like. Clicking a rendered block puts the cursor in it and hands the source
back; the HTML comment carrying an excalidraw sidecar is hidden outright, because it renders to
nothing. `layout="editor"` is the only layout with no preview pane and is what turns this on — the
full note page keeps its preview and its raw markdown.

**A rendered block is edited where it was clicked.** Swapping a block back for its source puts the
caret somewhere, and anywhere but under the pointer is wrong. At the block's start the first
keystroke landed in front of the opening fence — typing in a code block produced ```` X```python ````
and the code, the table and the math below it all fell back to source at once. At the block's last
line it landed on the closing fence, which is what threw the note around while editing an equation.

A click now answers with the character under it: code maps the pointer through the rendering, whose
text is the source's, to an offset in the block's body. A table answers with the clicked cell, not
the clicked row — the row's end is past the last pipe, which is no column at all, and typing there
was what looked like focus jumping away. A block whose first and last lines are fences — ``` and
`$$` — never hands back a caret on either of them. Being edited, a code block keeps its own dress,
so revealing the source is not a change of mode.

**A rendered block is one position to CodeMirror**, so vertical motion jumps the whole thing and a
table could only be entered with the mouse. Down and up put the caret on the block's first or last
line of content instead, which is what reveals it. Coming down the line below is the block's first,
coming up it is the block's last: a test for a decoration *starting* there finds only one of the two.

The preview pane on the full note page is a toggle, and live rendering follows it: hide the pane and
the same rendering appears there. It is reconfigured on a built view rather than read once at mount,
or the toggle would only take effect the next time the editor was rebuilt.

A drawn diagram carries the edit button the preview has, wired to the same `NoteDiagramDialog`. The
diagram is the image *and* the sidecar comment beneath it: rendered apart, the renderer sees an image
and offers no way into the scene, so the block is extended over both. The offsets it hands back are
relative to the block and are moved to the document before the note is rewritten.

Three things the grammar will not tell you. Block decorations may not come from a `ViewPlugin`
(CodeMirror throws), so the decorations are a `StateField`. `$$` blocks are found by scanning the
text, because the CodeMirror markdown grammar has no math extension. An HTML comment is `HTMLBlock`,
`CommentBlock` or `Comment` depending on whether it interrupts a paragraph, and hiding only the first
left the excalidraw sidecar on screen beside every diagram.

`make verify-dock` counts rendered quote lines for the rendering and the draft's own line count for
everything else, so taking the rendering away turns one check red rather than three.

**Nothing opens over the document.** The last three modals are panel faces. `ExplanationPanel` streams
a selection's explanation on its own face. `PracticePanel` is Practice, scoped to the selection that
opened it, to a section chosen on its own, or to the document — and clearing the scope is what
returns it to the document. `FeynmanPanel` takes the Practice face over while a session runs; the
panel is one column, so the summary the learner explains from is a collapsible strip above the tutor
rather than a pane beside it, and prose's own scale is overridden there because an `h2` at 24px in a
460px panel is a heading and no reference.

**Practice is a recall loop, not a generator.** The face opens on the deck for what is being read —
what is here, what is due — and `CardGenerator` sits below it, because a count field and a Generate
button answer a question the learner did not ask. A run's mode is fixed when it starts (`RecallRunner`
takes it as a prop) because `POST /study/teachback/async` rewrites its session's mode: offering both
inside one run would relabel it in the learner's own history.

Below the generator sit **the runs on this document** — the same `SessionHistory` rows the Study page
lists, from the same request, in both modes. A run started in the reader was otherwise findable only
from the Study page, and only if it was teach-back: the list filtered the other mode out, so the two
surfaces disagreed about what had happened on one document. Entering a run, deleting one and reading
its verdicts now mean the same thing from either view, and emptying the deck -- by replacing it or by
deleting it -- removes the runs it emptied from both (I-52).

The rule the loop enforces is that **the answer is not rendered until the learner has committed** —
a three-point confidence prediction, or an explanation typed out. Behind a `hidden` class it would
still be a panel you can read ahead in. Revealing puts the reading pane on the section the card came
from, which is the only reason to practise inside the reader rather than on the Study page. `again`
and `hard` hold on the revealed card with the source and the calibration line; `good` and `easy`
advance. Nothing here is new machinery: `prepareStudySession`, `submitReview`'s `predicted_rating`,
`useTeachbackPolling` and `InlineTeachbackFeedback` all already existed and the reader never called
them. `recallFeedback.ts` is what the Study page and the panel now share, so calibration — the number
the learner record is built on — is scored once rather than twice.

**A teach-back run is not graded by hand.** Scoring applies an FSRS review of its own
(`study.py:1529`), so the four grade buttons appear on recall cards and nowhere else -- offering
them on a scored card reviewed it twice. The reveal shows what the learner wrote, the expected
answer, the score and the rubric behind it, and `Next card` is available while the score is still
coming, with every attempt listed again in the run's summary so moving on early costs nothing.

`InlineTeachbackFeedback` renders all three rubric dimensions, each scored 0-100 as
`_RUBRIC_USER_TMPL` asks for (`study.py:284`) -- it used to show clarity's evidence alone, so the
two dimensions that move the score were fetched, stored and dropped. The rubric is a second,
best-effort LLM call and the panel says so when it comes back empty rather than showing nothing.

**A teach-back can be answered again**, on the card and from the finished summary, with the last
verdict kept in view to improve on. Retrying in place rather than discarding the attempt is not a
preference: deleting a session takes its teach-back rows and review events, and leaves the card's
FSRS state already advanced, so "delete and retry" would silently keep the schedule move it
appeared to undo. A card reached back out of the summary reopens the run's own session rather than
opening a second one for one card, and does not count as another card reviewed.

**Start starts; only the resume button resumes.** `prepareStudySession` adopts any open session for
the scope, which is right for the Study page -- it has no other way back into a run -- and wrong
here: pressing "Explain it" on a deck with cards due landed the learner in the summary of a run they
had finished days earlier. The deck names the open run and offers it explicitly, so the two intents
are separate and the start buttons always begin a fresh run.

**An interrupted run is offered back.** The deck names the most recent open session for the
document -- not a preferred mode, which offered a teach-back run abandoned days earlier over the
recall run left a minute ago -- and resuming reattaches by id, so a section run resumes as one. A
resume that lands on a different session is refused and said out loud, because
`prepareStudySession` otherwise falls through to creating a fresh run under a button that promised
the old one.

The source block says what was checked. `sourceNote` speaks for the quote and `answerCheckNote` for
the answer: the shipped state of most cards is `grounding=verified, factuality=unchecked`, and
"Found in this document" printed beside an unverified answer reads as an endorsement of it.

Only `GET /study/due` joins a section onto the cards it returns. A resumed session's remaining cards
(`study.py:1333`) and a deck run that was not due both arrive without one, so revealing resolves the
locus through `GET /flashcards/{id}/source-context` when the card does not carry it — otherwise the
jump silently disappears on exactly the second run of any deck.

The panel is dragged between 280 and 900px independently of the window, so a viewport breakpoint is
the wrong instrument: a centred `max-w-2xl` column carries the width, and the header sits over the
same column so nothing slides left when the panel is widened. Type follows the Study page rather
than the dock's old one-step-smaller scale — question at `text-lg` until the answer arrives, then
muted at `text-sm` above a rule with the answer at `text-base`.

Every face stays mounted and hidden, so switching tabs costs neither a streaming explanation nor a
half-written one. One ref carries where a transient face returns the panel, so closing an explanation
or a session lands back on whatever opened it.

**`readerSurfaces.test.ts` is what holds the claim**, because a browser check only ever sees the
modals a particular run happens to open: no file under `components/reader/` may import a dialog,
sheet, drawer or alert-dialog primitive, or be named for one, and the reader must mount all five
faces. The document's own delete confirmation is a popover and needs no exception. `make verify-dock`
fires the wiring instead — 63 checks, 71 with the teach-back arm and 67 with Feynman's. Each was fired on purpose: the
recall block goes red when the answer renders before the commit, when the reveal stops moving the
document, when a prediction is dropped, when committing stops revealing, and when the face leads with
the generator again.

The recall block grades nothing — predicting and revealing mutate no card — and deletes the study
session it opened, so it leaves the library as it found it. It needs a document with a card due and
says so when it finds none.

Its verdict check does not require a score: evaluation is a local LLM call that sometimes comes back
unscored, and a check that reddens on that is noise which would hide a real regression.

The teach-back arm is off by default and carries its reason next to the flag: submitting an
explanation has it scored, and scoring applies an FSRS review, so a run advances the schedule of
every card it touches. Deleting the session removes the review events and not the card state, so
nothing undoes it. `LUMINARY_VERIFY_TEACHBACK=1` is how that arm was measured.

The Feynman checks are off by default and say so next to the flag: `/feynman` has no delete, so each
run leaves a practice session in the library it runs against — two in dev, where StrictMode starts
the effect twice. `LUMINARY_VERIFY_FEYNMAN=1` re-enables them, and that is how the session's wiring
was measured.

The panel carries Insights, Ask AI, Notes, Practice and Explain. Of the seven faces this rung names,
Key Points, Detailed, Glossary and References are still folded into Insights; Explain is a face the
list did not anticipate, because an explanation of a selection has nowhere else to live, and it joins
the tab bar only while there is one to read.

Each face wears the icon its feature wears elsewhere -- `Brain` is the section row's Practice button
and the Recall arm, `MessageSquare` and `StickyNote` are the nav rail's own Ask and Notes -- so the
tab and the control that opens it read as one thing. Insights takes `ScrollText` and not `Sparkles`,
which is the Chat header's Creative toggle. Inside Insights, the speaker-turn summary is `Discussion`:
it was `Notes`, one row under the Notes face, which holds the reader's own writing instead.

A citation clicked in the docked conversation is answered beside it. `navigateToCitation` routed to
`/library?doc=...` unconditionally, which remounts the reader from the URL and takes the panel the
citation was clicked in down with it -- the passage arrives and the conversation is gone. The docked
conversation hands its citations to the reader first (`onCitationInDocument`), which marks the
passage and moves the left pane; a citation into a *different* document still routes, because there
is nothing beside it to show.

**The reader's header carries no panel tab.** It held a Practice button and a Chat button, each
opening a face the tab bar was already offering, and Practice's extra trick — arming the whole
document — is the Practice face's own "Use the whole document" control. `make verify-dock` reads the
header's own actions rather than the page's, because a section row carries a Practice button too.

A goal's Study button in `ChapterGoalsPanel` scopes the face to that goal's section instead of
leaving, and is now driven in a browser: the check finds a document that actually has an uncovered
goal rather than assuming the one the other checks read — objectives are extracted only from a tech
book's chapter openings, so keying it to that document would have skipped in silence forever. Taking
the section out of `handleStudyClick` turns it red at `This document`.

**A capture keeps where it came from.** `make verify-dock` takes a highlight from a recording and
reads back its `section_id` and the words it was taken from, identifying the new row by what was not
there before rather than by position — asserting the locus of the wrong row would pass while the new
one stored nothing. It then reloads, opens the reader's highlight list and finds the passage in it,
and deletes what it created. A note is still written in the panel, and the check says so.

**The nav is six rail items** — Home, Library, Notes, Study, Ask, Progress. This rung cut Ask from
it on the argument that a conversation with no scope is the one nobody asks for; that argument was
wrong in the case the rail exists to serve. A question across the whole library — compare two books,
search everything at once — has no other door, because a docked conversation is pinned to its
document and offers no scope picker by design. `/chat` was still routed the whole time, which in a
desktop app with no address bar is not the same as reachable. Map stays `full`; `blog` moves
`full` → `public`, because what a note becomes when it is shared is the point of writing one — which
also retires the build-time fold in `pages/Notes.tsx` that kept the publish dialog out of public
bundles. `surfaceManifest.test.ts` pins the rail to those six ids.

**Dictation rides on the transcriber that was already here.** `POST /audio/transcribe` hands a
browser recording to the same `AudioTranscriber` that ingests an audio file, so the mic in a note, a
teach-back answer and Ask needs no new weights and no new model. It does need the `transcription`
component, which the installer may not carry — faster-whisper pulls PyAV, whose wheels bundle
`libx264`/`libx265` — so the button reads a `dictation` capability and is absent until that is
installed. Without it a user records, waits, and is answered with a `uv sync` line.

**Both halves of microphone access are invisible until the app is signed.** `tauri dev` runs a bare
binary, which inherits the terminal's TCC grant and enforces no entitlement, so a mic button can be
built, demonstrated and shipped while the packaged app has neither `NSMicrophoneUsageDescription` nor
`com.apple.security.device.audio-input`. The first is not a denial but a **termination**: TCC kills a
process that reaches a protected device with no declared purpose. Both are now checked by
`verify_signed.sh` on the built artefact, and both were fired by stripping them from a signed bundle.
An entitlements plist may carry no XML comment — AMFI's parser rejects what `plutil` accepts.

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
