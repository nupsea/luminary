---
description: The two-lane orchestration model -- how Lumen connects study, concepts, and mastery into one loop. Read before working on any study/Hub/concept flow.
---

# The Two-Lane Model

Luminary already ships the hard parts (local ingestion, hybrid retrieval, FSRS, cited chat, a
knowledge graph, moded surfaces). What it lacked is **orchestration** -- the product saying *"here is
the one thing to do, and one door to do it from."* The two-lane model is that connective tissue.

## The loop

```
Hub says the one thing  ->  a Study Event does it  ->  results write to concepts
   ->  rollups / decay all move (derived, automatic)  ->  tomorrow's Hub reflects it
Notes deepen engagement  ·  Documents feed extraction  ·  Progress shows what's sticking
```

## The two lanes

| | **Lane A -- Lumen leads** | **Lane B -- you lead** |
|---|---|---|
| Trigger | time + state (decay, gates, misconceptions) | you, from anywhere |
| Unit | **concepts** (Lumen's first-class lens) | **any scope** (collection · tag · doc · note · selection · chat) |
| Output | the daily call on the Hub | a generated study event on demand |
| Writes back | **identical** -- one assessment pipeline, one set of files |

Concepts are how Lumen *tracks and drives* proactively; generation is open to **any** scope on
demand. Mastery still accrues only to [concepts](concepts.md) (rollups stay computed); questions
generated from a scope that maps to no concept become **unmapped cards** -- fully functional,
mapped later.

Both lanes converge on the [Study Launcher](study-launcher.md): every study handle in the app
opens the same pre-filled sheet and starts a **Study Event**.

## Study Events (the assessment atom)

"Session" generalizes to **Study Event** -- the umbrella unit of assessment. All four kinds write
through **one pipeline** -> `sessions/*.json` transcript -> `memory.md` digest line.

| Kind | What | Writes |
|---|---|---|
| `full_session` | warm-up -> engage -> reflect (+ teach-back in full mode) | FSRS, calibration, (teach-back coverage) |
| `quick_quiz` | 5-10 generated questions, one screen | FSRS, calibration |
| `drill` | 3-min misconception fixer | FSRS, misconception status |
| `checkpoint` | inline retrieval while reading | FSRS (light), signals |

Calibration aggregates only events with >=4 rated items (avoids micro-quiz noise).

## Unmapped cards

A saved card whose question matches no tracked concept yet. **Fully functional** -- FSRS schedules
it; it appears in warm-ups under its scope's name. Periodically Lumen proposes a mapping ("these 5
cards look like *event sourcing* -- track it?"). Until mapped it does **not** feed collection
rollups (constitution rule 3). Shown as "loose cards · N" on the collection page.

- Schema: `flashcards.concept_id` is **nullable**; `flashcards.source_scope` (text) +
  `flashcards.mapping_status` (`mapped | unmapped | proposed`).

## Candidate concepts

A concept proposed from **non-document** material (notes, quiz clusters, chat, OKF import). Stays
`candidate` -- excluded from gap/route participation -- until a document covers it **or** the user
confirms. Keeps the doc-grounded graph honest while letting user material lead. See the
[concept lifecycle](concepts.md#lifecycle).

## Extraction vs generation (keep distinct)

- **Extraction** (Lane A, automatic) reads **documents only** -> builds the durable graph.
- **Generation** (Lane B, on demand) reads **anything in scope** -> builds questions.
- Notes never silently extract; they generate when asked.

## The constitution (14 rules -- every PR is checked against these)

1. **Concepts are Lumen's first-class lens, not the user's cage.** Proactive surfaces run on concepts; generation runs on any scope on demand.
2. **One engine, many doors.** Every study handle opens the same launcher; every event writes one pipeline.
3. **Mastery lives on concepts; everything else is a computed rollup.** Unmapped cards work fully but feed rollups only once mapped.
4. **Extraction is document-driven; generation is scope-driven.** The durable graph stays grounded in citable sources.
5. **Everything Lumen makes is proposed, evidenced, correctable.** Provenance always; corrections survive re-parse.
6. **One call at a time.** Hub makes one recommendation with a *because*; "done for today" is a real state; no surface nags.
7. **Activity is never mastery.** Read-% is cosmetic; the mastery number requires retrieval.
8. **The learner model is files the user can read, edit, delete.** (OKF-backed -- see [okf.md](okf.md).)
9. **Local by default, degraded gracefully.** Model down => review, reading, notes, manual cards still work.
10. **Every surface earns its place by routing to action.** Can't launch a study event, link material, or correct the graph in one tap => it's decoration.
11. **The manifest is law.** Every surface declares a mode; core (public) never hard-depends on a full-mode feature.
12. **Don't invent over what ships -- extend it.** New surfaces enter labelled; full-mode-first where unproven.
13. **Transport and knowledge are separate layers.** LiteLLM carries bytes; OKF carries portable knowledge. Never couple.
14. **Local-first is a hard floor, not a default.** No external dep without a local alternative; never transmit user content to telemetry.

## Per-mode behavior matrix (public / full)

The model must behave correctly in both [surface modes](../surface-manifest.json). Public never
hard-depends on a full-mode feature -- it degrades (constitution 9, 11; invariant I-10).

| Capability | public | full |
|---|---|---|
| Concept extraction (document-driven) | yes | yes |
| Mastery / FSRS / Study Events | yes | yes |
| Study Launcher + all entry points | yes | yes |
| Concept vector (centroid) for linking/dedup | yes | yes |
| Within-collection concept linking | yes (after quality bar) | yes |
| Cross-library concept linking | -- | yes |
| Clustering / org-plan suggestions | -- | yes |
| Pomodoro focus pill | -- | yes |
| Teach-back / Feynman (4th session phase) | -- | yes |
| Web/URL, YouTube, audio, image, tech-book ingest | -- | yes |
| OKF export / grounding / import | yes (public router) | yes |
| Blog publish (reframed as OKF share) | -- | yes |
| Code executor, dataset generator | -- | yes |
| Map (tag/concept graph) | -- | yes |

Degrade rule: model down -> due-card review still starts, generation disabled with the shipped
banner; note concept-chips fall back to title/centroid-vector match.

## Where the pieces live

- [concepts.md](concepts.md) -- the Concept primitive (the studyable atom).
- [study-launcher.md](study-launcher.md) -- one sheet, many doors; `POST /study/assemble`.
- [okf.md](okf.md) -- portable knowledge projection.
- [architecture.md](architecture.md), [invariants.md](invariants.md) -- the hard rules.
