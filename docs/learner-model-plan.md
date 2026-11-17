---
description: Plan for the learner model - Lumen reads what Luminary has measured about the learner, relative to their library, and uses it in Ask, retrieval and suggestions. Not scheduled. Deleted once it ships.
---

# Learner model

Lumen answers every question as if it had never met the learner. Luminary already measures what
they have read, asked, carded, retained and got wrong, section by section, and none of it reaches
Ask. The learner model routes that record into the moments where it helps, and lets the learner see
and correct everything Lumen believes about them.

Status lives in `roadmap.md` ("Deferred"); this file is the plan and is deleted when the work ships.

## When to pick it up

The work is staged so any stage can ship alone. Before 1.0, a stage moves onto a 0.x rung only by
displacing planned work of equal size (`roadmap.md`, "Room for new issues").

| Stage | Fits before 1.0 when | Otherwise |
|---|---|---|
| 0. Working context | Already on 0.20.0 as #441 / #440; extend those issues, no new slot | — |
| 1. Measured read model | An iteration has a free lane and #441 has landed | 1.1.0 |
| 2. Stated profile + "What Lumen knows" | Stage 1 shipped and its eval arm is green | 1.1.0 |
| 3. Inferred observations | Never before 1.0 | 1.1.0 or later |
| 4. Personalised defaults | Never before 1.0 | after stage 3 has a confirmation rate worth trusting |

## The rule the design follows

**Lumen's beliefs about the learner are held to the same standard as its answers: each one names
its evidence, its confidence and when it was last true, and the learner can see and overrule it.**
A profile the model writes and then reads back is the model confirming itself
(`.claude/rules/common/product-integrity.md`).

## Three kinds of knowledge

| Kind | Examples | Source | May shape an answer |
|---|---|---|---|
| **Measured** | retention per section, open misconceptions, sections read, calibration | derived at read time from existing tables, never copied into a new one | yes |
| **Stated** | goals, deadlines, answer preferences ("code first, short") | the learner | yes; overrides the other two |
| **Inferred** | "keeps returning to lifetimes", "studies late evening" | a consolidation job | no; suggestions only, until the learner confirms it, which makes it stated |

Stated-overrides-measured already exists twice: `facets_source = "reader"` (#346) and
`OverrideModel`. Reuse that shape rather than a third mechanism.

## The unit is the section

The learner model is a matrix of the learner against their library's sections: read, asked about,
carded, retained, misconceived. Sections are authored headings, so the matrix cannot drift into
inferred vocabulary. Concepts are not the unit: bottom-up clustering produced labels that were
not knowledge (Universe, `roadmap.md` "Abandoned").

## Signals that exist today

| Signal | Table | Reaches a section through |
|---|---|---|
| Reviews, FSRS state | `review_events`, `flashcards` | card `chunk_id` (the quote's chunk, I-35) -> chunk's section |
| Misconceptions (open/resolved) | `misconceptions` | `flashcard_id` -> card -> section |
| Teach-back results | `teachback_results` | session scope |
| Calibration | `review_events.predicted_rating`, `prediction_events` | card / `chunk_id` |
| Reading | `reading_progress`, `reading_positions`, `time_on_task` | `section_id` directly |
| Questions | `qa_history`, `chat_messages` | **cited chunks only** |
| Goals | `learning_goals` | `document_id` / `collection_id` |
| Suggestion response | `recommendation_feedback` | target ref |

A question is not linked to what it asked about, only to what the answer cited. A question the
library could not answer has no section at all. Stage 1 must decide whether to store the retrieval
scope on the question, or accept that a missed retrieval reads as "never asked".

Existing consumers: `recommender_service` already reads weak concepts, open misconceptions,
calibration blind spots and stalled reading for the Hub. Ask reads none of it.
`qa._maybe_rewrite_query` uses only the previous user turn and graph entity names.

## Stages

### 0. Working context (on 0.20.0)

Fold the reader's position (open document, section, selection) into #441's standalone rewrite, so
"what does he mean here" resolves against where the learner is. Done when #440's multi-turn golden
set scores deictic follow-ups above the no-position arm on two runs.

### 1. Measured read model

A `learner_context` service (Service layer) returns, for a scope (section, document or collection),
the measured facts with the `metrics.md` contract: sample size, definition, basis, `null` never `0`.
No LLM call, no new table.

Ask uses it to set the explanation level: skip basics the learner has retained, name an open
misconception the answer touches. Retrieval may give the section being read or studied a soft
boost, never a filter, through the `retrieval-change` skill.

Done when, memory on against memory off over the Ask goldens, grounding and citation rates do not
fall, and a blind pairwise preference by the learner favours memory on.

### 2. Stated profile and "What Lumen knows"

The learner states goals, deadlines and answer preferences. A view lists every fact Lumen would use,
each linked to its evidence, each correctable or removable. An "Ask without memory" toggle is both
the privacy control and the comparison arm.

### 3. Inferred observations

A consolidation job reads the episodic record and writes observations, each with evidence ids,
confidence, `first_seen` / `last_seen`, and decay. They surface only as suggestions with their
evidence: "four questions about lifetimes, no cards on that section; make some?" Confirming one
makes it stated; rejecting one is recorded so it is not re-proposed.

Two suggestion kinds come from questions:

- **Learner gap**: a section asked about repeatedly with no cards or low retention.
- **Library gap**: questions the library could not answer, kept as a list of what the library does
  not cover; a natural input to the connectors (`connectors.md`).

Done when a hand-graded sample of observations, read against their evidence, has a precision the
maintainer accepts, and the learner's confirmation rate is reported beside it.

### 4. Personalised defaults

Hub ordering, session length and study time drawn from stated and confirmed facts only.

## Rules

- Personalisation changes emphasis and level, never what is claimed. Citations and grounding checks
  are identical with memory on and off.
- Inferred facts never enter an answer prompt. Only measured and stated facts do.
- Never a retrieval filter from the learner model, only a soft prior: a filter hides weak areas,
  which a retention product exists to surface.
- No LLM-extracted ontology over the learner or the library. Prerequisite extraction returned `[]`
  on 50 of 50 sections (`roadmap.md`, "Abandoned").
- Everything lives under `library_root()` and travels with the snapshot (a new folder joins
  `storage.LIBRARY_FILE_DIRS`). Libraries never share a learner model.
- In hybrid or cloud mode, any learner fact sent to a provider is named on the privacy receipt
  (`llm_routing.routing_report`). A learner fact is more sensitive than a chunk.
- Observations decay. Nothing about the learner is a permanent label.

## Open questions

- Does stage 1 need a question-scope column on `qa_history` / `chat_messages` (a migration, I-23),
  or is the cited section enough?
- Should the learner model be exposed by the read-only MCP server (#349)? Default: no.
- Answer-level shaping on the 4B local model: does adding learner facts to the prompt cost grounding
  at that size? Measure before assuming.
