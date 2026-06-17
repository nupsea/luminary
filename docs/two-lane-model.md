---
description: The two-lane orchestration model -- the spine of the Knowledge Universe redesign. Read before working on any study/Hub/concept flow.
---

# The Two-Lane Model

The spine of the Knowledge Universe redesign. Luminary already ships the hard parts (local
ingestion, hybrid retrieval, FSRS, cited chat, a knowledge graph, tiered labs). What it lacked is
**orchestration** -- the product saying *"here is the one thing to do, and one door to do it
from."* The two-lane model is that connective tissue.

> Source of truth: `docs/handoff/implementation-plan/` (the build-ready bundle).
> `docs/KNOWLEDGE_UNIVERSE.md` is the conceptual north star (reference, not law). See
> [Spec reconciliation](#spec-reconciliation).

## The loop

```
Hub says the one thing  ->  a Study Event does it  ->  results write to concepts
   ->  rollups / decay / graph warmth all move (derived, automatic)  ->  tomorrow's Hub reflects it
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
| `full_session` | warm-up -> engage -> reflect (+ teach-back if Feynman labs on) | FSRS, calibration, (teach-back coverage) |
| `quick_quiz` | 5-10 generated questions, one screen | FSRS, calibration |
| `drill` | 3-min misconception fixer | FSRS, misconception status |
| `checkpoint` | inline retrieval while reading | FSRS (light), signals |

Calibration aggregates only events with >=4 rated items (avoids micro-quiz noise).

## Unmapped cards

A saved card whose question matches no tracked concept yet. **Fully functional** -- FSRS schedules
it; it appears in warm-ups under its scope's name. Periodically Lumen proposes a mapping ("these 5
cards look like *event sourcing* -- track it?"). Until mapped it does **not** feed collection/goal
rollups (constitution rule 3). Shown as "loose cards · N" on the collection page.

- Schema: `flashcards.concept_id` is **nullable**; `flashcards.source_scope` (text) +
  `flashcards.mapping_status` (`mapped | unmapped | proposed`).

## Candidate concepts

A concept proposed from **non-document** material (notes, quiz clusters, chat, OKF import). Stays
`candidate` -- dimmer star, no gap/route participation -- until a document covers it **or** the
user confirms. Keeps the doc-grounded graph honest while letting user material lead. See the
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
11. **The manifest is law.** Every surface declares a tier; core never hard-depends on a labs feature.
12. **Don't invent over what ships -- extend it.** New surfaces enter labelled; labs-first where unproven.
13. **Transport and knowledge are separate layers.** LiteLLM carries bytes; OKF carries portable knowledge. Never couple.
14. **Local-first is a hard floor, not a default.** No external dep without a local alternative; never transmit user content to telemetry.

## Per-tier behavior matrix (public / labs / dev)

The model must behave correctly in all three [surface tiers](../surface-manifest.json). Core never
hard-depends on a labs feature -- it degrades (constitution 9, 11; invariant I-10).

| Capability | public | labs | dev |
|---|---|---|---|
| Concept extraction (document-driven) | yes | yes | yes |
| Mastery / FSRS / Study Events | yes | yes | yes |
| Study Launcher + all entry points | yes | yes | yes |
| Concept vector (centroid) for linking/dedup | yes | yes | yes |
| Within-collection concept linking | yes (after D7 quality bar) | yes | yes |
| Cross-library concept linking | -- | yes | yes |
| Clustering / org-plan suggestions | yes | yes | yes |
| Pomodoro focus pill | yes (quiet, in Study chrome) | yes | yes |
| Universe lens (baseline sky + warmth) | yes | yes | yes |
| Universe dense concept-edge web | only if within-collection linker on | yes | yes |
| Teach-back / Feynman (4th session phase) | -- | yes | yes |
| Web/URL, YouTube, audio, image, tech-book ingest | -- | yes | yes |
| OKF export / grounding / import | yes (public router) | yes | yes |
| Blog publish (reframed as OKF share) | -- | yes | yes |
| Code executor, dataset generator | -- | -- | yes |

Degrade rules: model down -> due-card review still starts, generation disabled with the shipped
banner. `concept_linker` off -> Universe shows independent warm/cool stars (never blank); note
concept-chips fall back to title/centroid-vector match.

## Spec reconciliation

`docs/handoff/` is **authoritative**. `docs/KNOWLEDGE_UNIVERSE.md` is the earlier, purist spec
kept for conceptual grounding. Where they differ:

- KU says concepts come from **documents only**; notes merely *link*. The handoff bundle keeps
  documents authoritative but adds **candidate concepts** (origin `note|quiz|chat|import`) that
  stay dimmer until a doc covers them. The bundle wins.
- KU caps mastery at 80 without teach-back. The bundle **removes** that cap (it hard-coupled core
  to a default-off labs feature -- constitution 11). The bundle wins.

Both agree on the non-negotiables: **mastery lives only on concepts**; **everything Lumen makes is
proposed/evidenced/correctable**; **activity is never mastery**.

## Where the pieces live

- [concepts.md](concepts.md) -- the Concept primitive (the studyable atom).
- [study-launcher.md](study-launcher.md) -- one sheet, many doors; `POST /study/assemble`.
- [universe.md](universe.md) -- the Knowledge Universe lens.
- [okf.md](okf.md) -- portable knowledge projection.
- [architecture.md](architecture.md), [invariants.md](invariants.md) -- the hard rules.
