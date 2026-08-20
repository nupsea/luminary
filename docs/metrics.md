---
description: Every user-facing number in Luminary -- its formula, its window, and the sample below which it is not reported.
---

# Metrics

Every number the product shows a learner is computed server-side and arrives with
the definition it was computed from. `GET /progress/summary` returns each as a
`Metric`:

| Field | Meaning |
|---|---|
| `value` | The number, or `null` when it could not be computed |
| `unit` | `percent` \| `count` \| `days` \| `minutes` |
| `sample_size` | What it was computed from |
| `definition` | One sentence, rendered in the card's info popover |
| `basis` | The concrete evidence, or the reason `value` is null |

**A metric that could not be computed is `null`, never `0`.** "You have reviewed
nothing" and "your retention is 0%" are opposite statements, and a zero standing
in for the first is the defect this contract exists to prevent. `MetricCard`
(`frontend/src/components/ui/metric.tsx`) renders `null` as an em dash with the
`basis` beneath it. This is I-32 applied to the surfaces a learner reads.

## The metrics

| Metric | Formula | Window | Reported from |
|---|---|---|---|
| `retention_30d` | correct reviews / total reviews | 30 days | 20 reviews |
| `mastery` | Bloom-weighted mean of `min(fsrs_stability / 21, 1)` over cards with `reps > 0` | all time | 10 reviewed cards |
| `mature_cards` | count of `fsrs_state = 'review' AND fsrs_stability >= 21` | all time | 1 reviewed card |
| `due_today` | count of `due_date <= now` | — | always |
| `current_streak` / `longest_streak` | stored on `study_streaks`, written by the assessment pipeline | — | always |
| `reviews_30d` | count of `review_events` | 30 days | always |
| `gaps_closed` | misconceptions with `status = 'resolved'` | all time | always |
| `time_on_luminary` | sum of `time_on_task.seconds` | 7 days | 1 recorded second |
| `active_days` | distinct local days carrying a review or a recorded interval | 7 days | always |
| `documents` / `notes` | `COUNT(*)`, notes excluding archived | — | always |

Thresholds live in `backend/app/services/progress_service.py`, each next to the
two cases that bracket it.

## Mastery

Mastery is FSRS stability, not answer accuracy. A card's stability is the interval
at which it stays recallable, so `min(stability / 21, 1)` reads as "how close this
card is to surviving three weeks away". Cards testing analysis (`bloom_level >= 4`)
weigh 1.5.

This is the formula the assessment pipeline writes to `concepts.mastery`
(`MasteryService._compute_weighted_mastery`, I-19). The library headline reuses
that function rather than deriving a second one, so the two cannot disagree.

Two properties are load-bearing:

- **Only cards with `reps > 0` count.** A generated-but-unreviewed card has
  stability `0.0`. Counting new cards would make the number mean "share of my
  library I have got round to", which falls as fast as a learner generates cards.
- **No prediction-error penalty.** The concept-level formula subtracts one, capped
  at 0.20. Applied across a whole library any four errors max it out, so it would
  describe library size rather than the learner.

**Accuracy over recent sessions is not mastery.** The Progress page averaged
`accuracy_pct` across the last 50 study sessions, unweighted by session size, so a
single 10-card session at 90% rendered as "90% mastery" on a fresh install. That
scenario reproduced against this formula reads 7.1% — ten cards at 1.5 days'
stability against a 21-day bar — which is what one sitting has actually bought.

## Time on task

`time_on_task`, written only by `TimeOnTaskService`, drawn as the hub's weekly
split across `note`, `document`, `review` and `study`.

**It measures time with a surface open and visible, which is not attention.**
Nothing may relabel it "time studied" or "time reading". The server cannot
measure this at all — a reader who opens a document and reads for twenty minutes
issues one request — so the client samples every 15s from `useTimeOnTask`, and
stops while the tab is hidden.

Two rules keep the number from inventing time:

- **Credit is the gap between consecutive beats, never the beat itself.** A first
  beat is worth zero because nothing precedes it to measure from.
- **A gap over `MAX_CREDITED_GAP_SECONDS` is credited as nothing.** Bracketing
  cases sit next to the constant: 20s is one slow round trip on a busy machine and
  is real; 60s means the tab was hidden or the user left. Without this ceiling a
  backgrounded tab banks every second it was away.

A row is an interval rather than a beat, so a session costs about one row. The
weekly split is zero-filled across all four activities: a missing slice is
indistinguishable from a measured zero otherwise.

`WeeklyStats.minutes_studied` sits beside it and is **a different basis** —
study-session wall clock from `study_sessions.started_at..ended_at`. The two are
not interchangeable and the ring never mixes them, or its wedges would sum to
something that is not its total.

`backend/tests/test_time_on_task.py` fails CI if a discontinuous gap is credited,
if the ceiling drifts outside its two bracketing cases, or if an unknown activity
is recorded instead of refused. `scripts/smoke/S240.sh` checks the wire contract.

## What is deliberately not computed

**There is no efficiency, focus or productivity score**, and the reason is the
shape of the data rather than the difficulty of the formula.

Every such score is a ratio with time underneath it — cards per minute, retention
per hour, "focus %". The only time signal in the product measures *a surface being
open and visible*, so any ratio built on it inherits a denominator that cannot
tell reading from a tab left open behind a lunch break. The output would carry two
decimal places and mean nothing, and it would be believed precisely because it
looks computed. That is the failure `.claude/rules/common/product-integrity.md`
exists to prevent, arriving as a feature rather than a bug.

`active_days` is what survives the same question honestly: a day is active if it
carries a graded review or a recorded interval. Both are direct observations,
there is no weighting, and a reader can check it against their own week.

If an effort-weighted mastery is wanted later, the honest version weights by
**answers graded**, which is observed, and never by time, which is sampled. State
that in the definition before building it.

## Prediction calibration

`GET /study/calibration-stats`. Study asks you to predict your grade before the
answer is revealed; the match rate is how often
`ReviewEventModel.predicted_rating` equalled the grade you then gave, over 30
days. It measures self-knowledge, not recall: a learner can score 60% retention
and be perfectly calibrated about which 40% they will miss.

## Streaks

One source: `study_streaks`, via `GET /engagement/streak`. Recomputing a streak
client-side from a 30-day history window reads `0` for anyone who has not studied
yet today and truncates any run longer than the window — the Progress page did
both, while `StudyHabitsSection` on the same page showed the stored value.

## Adding a metric

1. Compute it in `ProgressService`, returning a `Metric`.
2. Give it a minimum sample if it is a rate, and name the two cases that bracket
   the threshold next to the constant.
3. Return `_absent(...)` below that sample. Never `or 0.0`.
4. Add it to `ProgressSummaryResponse`, to the table above, and to
   `scripts/smoke/S238.sh`, which fails if any metric ships without a definition
   or a basis.

`backend/tests/test_progress_summary.py` fails CI if an uncomputable metric
returns a number, if new cards drag mastery down, or if one good session reads as
a mastered library.
