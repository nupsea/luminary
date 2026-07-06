---
description: Personal recommender spec -- deterministic, evidence-grounded next-best-action on the hub plus misconception lifecycle. Read before implementing on feat/personal-recommender.
---

# Personal Recommender

Branch: `feat/personal-recommender`. Status: approved scope, ready to implement.

## The value, in one sentence

The hub answers "what should I do next, and why?" from evidence the app has actually
measured, and when the learner closes a gap the app notices and says so.

## Scope decisions (locked 2026-07-06)

- **In**: hub recommender (hero + up to 3 secondary cards, each with a because-line and a
  dismiss control), misconception lifecycle (open -> resolved), persistent
  dismiss/acted feedback table.
- **Out -- do not let these creep back in**: `learner_facts` table, LLM consolidation
  jobs, Ask/chat learner-context injection, study-assembler re-weighting, acceptance-rate
  dashboards. Some may become follow-up branches; none are designed into this one.

Two hard rules:

1. **Deterministic at request time.** Candidate generation and scoring are plain DB reads.
   No LLM anywhere in this feature.
2. **Document-agnostic.** No subject, corpus, or document special-casing in generators,
   weights, or thresholds.

## Current state

`_pick_today_action` in `routers/home.py` is a fixed 3-rule priority (due cards >
continue-reading > resume-note). It ignores mastery, `again` streaks, misconceptions, and
calibration deltas -- all of which are already collected. `misconceptions` rows are
write-only today (written in `routers/study.py` answer grading, never read back).
`fsrs_service.py` already computes struggling cards (`again_count >= threshold` over
recent `review_events`).

## Design

### `recommender_service`

`backend/app/services/recommender_service.py`, one entry point:

```
async def get_recommendations(session: AsyncSession, limit: int = 4) -> list[Recommendation]
```

`Recommendation` (Pydantic, in the home schemas module): `kind`, `target_type`,
`target_ref`, `label`, `score`, `reasons: list[Reason]`, `action` (deep-link payload for
`luminary:navigate`). `Reason` = `{signal, value, detail}` -- enough to render an honest
because-line, e.g. "3 reviews rated 'again' this week on *B-tree splits*".

Five generators, each a small async function over existing tables, run **sequentially on
the one request session** (I-1 -- no gather):

| Generator | Signal source | Deep link |
|---|---|---|
| `overdue_reviews` | due count + max days overdue on `flashcards` | Study daily scope |
| `weak_concept` | `concepts.mastery` below floor joined with recent `again`/`hard` `review_events` via `flashcards.concept_slug` (reuse the fsrs_service struggling query) | concept-scoped study |
| `open_misconception` | `misconceptions` where `status='open'`, ranked by age x error_type | re-quiz that flashcard's concept |
| `calibration_blind_spot` | `review_events.predicted_rating` >> actual, aggregated per concept over last N reviews | confidence-check drill on concept |
| `stalled_reading` | `reading_progress` in (0,1) with no `content_activity` for N days | continue reading |

Scoring is a transparent weighted sum:

```
score = w_u * urgency + w_i * impact + w_r * recency - w_f * fatigue
```

urgency = time-sensitivity (FSRS overdue days, misconception age); impact = mastery
deficit / error severity; recency = warm context bonus (recently touched doc or concept);
fatigue = penalty from prior un-acted `shown` rows in `recommendation_feedback`.
Weights and thresholds are module constants with unit tests, not settings. Dismissed
targets are excluded outright while their dismissal is active.

The top-scored candidate becomes `today_action` (same `TodayAction` contract, extended
with optional `reasons`); the next up-to-3 fill a new `recommendations` list on the
overview response. When no generator fires, behaviour degrades to exactly today's
heuristics (continue-reading / resume-note fallbacks stay as the floor).

### Table: `recommendation_feedback`

```
id TEXT PK, kind TEXT, target_type TEXT, target_ref TEXT,
shown_count INTEGER DEFAULT 0, last_shown_at DATETIME,
dismissed_at DATETIME NULL, acted_at DATETIME NULL
```

One row per (kind, target) -- upserted on show, stamped on dismiss/act. Serves anti-nag
(dismiss persists; fatigue grows with un-acted shows) and leaves an honest usage record.
Dismissal expires when the underlying signal materially changes (e.g. new `again` review
after dismissal re-arms the target); expiry rule lives in the generator, not the table.

Endpoints (on the existing `home` router -- no new router, no surface-manifest churn):

```
POST /home/recommendations/{id}/dismiss
POST /home/recommendations/{id}/acted     (fired by the frontend on click-through)
```

### Misconception lifecycle

- `ALTER TABLE misconceptions ADD COLUMN status TEXT NOT NULL DEFAULT 'open'` and
  `ADD COLUMN resolved_at DATETIME` via the existing idempotent migration list in
  `db_init.py`.
- **Resolution is deterministic, no LLM**: when a review event with rating good/easy or a
  passing teach-back lands on a flashcard that has open misconceptions, mark them
  resolved. Hook = the existing review-write path in `routers/study.py` /
  `repos/study_repo.py` (single call into the service; keep the router thin).
- Resolved misconceptions stop feeding `open_misconception` and surface on Progress as a
  simple "gaps closed" count (one stat, reuse an existing Progress stat slot -- not a new
  widget system).

### Hub UI (`frontend/src/pages/Hub.tsx`)

- TodayHero keeps its layout; gains a one-line muted because-line under the CTA.
- New "Recommended next" stack under the hero: up to 3 compact cards -- icon per kind,
  label, because-line, dismiss (x). Click-through fires `acted` then navigates via
  `luminary:navigate` (I-11).
- States per I-10: skeleton while loading, inline error, and when empty the section
  disappears entirely (the hero fallback always renders something).
- Data rides the existing `GET /home/overview` single-fetch contract -- no extra hub
  query beyond the two mutation calls.

## Implementation order

1. **Schema**: `recommendation_feedback` model + DDL; `misconceptions` status columns via
   the `db_init.py` ALTER list.
2. **Misconception resolution** in the review/teach-back write path + tests (open ->
   resolved on good review; stays open on `again`).
3. **`recommender_service`**: generators + scoring + fatigue/dismiss filtering. Unit
   tests per generator (seeded SQLite fixtures) + scoring-order tests.
4. **Router**: extend `/home/overview` response (`today_action.reasons`,
   `recommendations`), add dismiss/acted endpoints. API contract tests.
5. **Frontend**: types, hub stack + hero because-line, dismiss/acted wiring, I-10 states.
6. **Progress**: "gaps closed" stat.
7. **Gates**: ruff -> pytest -> tsc (I-13), then a live drive of the hub with a seeded DB
   (due cards + an open misconception + a calibration gap) verifying ranking, dismiss
   persistence across reload, and resolution flow end to end.

Each step lands green before the next starts; the feature is inert until step 4-5 exposes
it, so there is no broken intermediate state.

## Invariants in play

I-1 (generators share the request session sequentially, never across `gather`), I-10/I-11
(hub UI), I-13/I-14 (gates before done), I-19 (read `concepts.mastery`, never recompute),
six-layer rule (SQL in service/repo, router stays thin).
