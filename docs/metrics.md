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
