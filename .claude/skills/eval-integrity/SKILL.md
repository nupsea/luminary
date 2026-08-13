---
name: eval-integrity
description: How to change, generate or read an eval in this repo without producing a number that cannot be trusted — goldens, thresholds, the quality gate, and the failure modes that make a metric lie. Use whenever touching evals/, a golden .jsonl, a threshold, or when about to quote an eval number in a decision.
---

# Eval integrity

An eval number is a claim about the product. A wrong one is worse than no number, because it
gets spent: a model gets chosen, a change gets shipped, a plan gets written on top of it.

**The rule: a number you cannot explain the provenance of does not enter a decision.**

## Before quoting any eval number

Answer these three. If you cannot, the number is not usable yet.

1. **Which dataset, and is that dataset clean?** Run the audit below. A dataset can be
   structurally broken and still produce a confident-looking float.
2. **Was the metric computed, or defaulted?** `null` is not `0.0` and neither is a pass.
3. **What is it being compared against?** A floor is a collapse detector. Only a delta against
   your own baseline — same dataset, same day, same ingestion state — measures a change.

## What makes a golden trustworthy

A retrieval golden is a set of (question, hint) pairs where the hint names the passage the
question was authored from. Four properties, all mechanically checkable:

| Property | Why it matters | Failure it causes |
|---|---|---|
| The hint resolves in the corpus | `HINT_NORM_LEN=80`-truncated substring match | Question is permanently unhittable; floor becomes a golden artifact |
| The hint occurs **exactly once** | A hit must mean "found *that* passage" | A hit is credited for retrieving any duplicate — the metric measures nothing |
| The question is about the document | Not about scrape furniture, a license appendix, a nav menu | Unique junk tokens are trivially findable; the score inflates |
| Questions are distinct | Near-duplicate questions gate on one passage | The dataset is smaller than its row count claims |

The audit is in `evals/audit_golden.py` for live retrieval, but hint uniqueness and furniture
contamination are checkable offline against the source file — do that first, it needs no
backend.

Read the corpus through `app.services.source_text.read_source_text`, never `read_text()`.
That is the ingestion path. **A generator that reads the raw file writes questions about text
that never becomes a chunk** — this is exactly how 17 of 40 `paper` questions came to ask
about a scraped 404 page.

## What a metric may never do

- **Never pass because it could not be computed.** A judge that failed to load, an NLI model
  that did not score, a `/qa` call that timed out — each yields `None`, and a `None` that is
  silently skipped records `passed: true` for a run that measured nothing. Requested-but-
  uncomputed is a **failure**. Not-requested is a skip. These are different states.
- **Never fabricate a default.** No `or 0.0`, no `or 1.0`, no filling a missing judge verdict
  with a neutral score. A summary-eval judge failure once returned 1.0.
- **Never blend into one score.** HR@5 and MRR move independently — a change can find more and
  rank it worse. Report both.

## Reading the metrics honestly

- **HR@5** — recall-shaped: was the passage in the top 5.
- **MRR@5** — ordering-shaped: how high the first match ranked.
- **nDCG@10** — graded, needs a `relevance` field. Without one it silently degrades to a
  log-discounted single-hit metric. Check whether the dataset actually has grades before
  reporting nDCG as a graded number.
- **Faithfulness (HHEM)** — a **within-model** signal. Cross-model deltas are a style artifact
  and must never gate a model decision.

Substring matching cuts both ways: a chunk that answers the question in different words scores
a **miss**. The retrieval metrics understate as often as they overstate — they are a proxy for
"did the funnel surface the authored passage", not for answer quality.

**No retrieval metric contains a generation-model term.** HR@5 cannot rise because a better
model was swapped in. Including retrieval metrics in a model comparison lets retrieval noise
be attributed to the model.

## Re-measure the baseline after any corpus change

Retrieval scores for one document can move when a *different* document is ingested or deleted.
Measured 2026-08-12: deleting and re-ingesting `paper` moved `book`'s MRR from 0.4104 to
0.3979 with nothing about `book` touched, both values bit-reproducible either side. That is the
same magnitude as the entity-model difference measured on `paper`, so that difference was
indistinguishable from a library-state change.

**The coupling is real but not universal, and the mechanism is not established.** Adding three
documents and ~4,870 chunks afterwards moved `book` and `paper` by exactly zero. Two candidate
mechanisms are in the code and neither has been isolated: `bm25(chunks_fts)` scores over the
whole FTS table with the `document_id` filter applied to matched rows (`retriever.py:225`), so
term statistics are corpus-wide; and graph expansion reads an entity graph that every ingest
rewrites. Do not repeat either as the cause without an experiment that separates them.

The operational rule does not depend on knowing which: **an A/B is only valid if the corpus did
not change between the arms, and if it did, re-run the baseline arm rather than comparing
against an earlier number.**

## Dataset size sets the resolution

A dataset of *n* rows moves HR@5 in steps of `1/n`. At 5 rows one question is 20 points, which
is not a gate against a 0.50 threshold — it is noise with a decimal point. Check the row count
before trusting a delta, and check `accepted` vs `target` in the `.meta.json`: a dataset that
shipped under target was not filled, and nobody decided that was fine.

## Regenerating a golden

Needs `OPENAI_API_KEY` + Ollama. Overwrites committed files — say so before running it.

```
make golden-paper      # or golden-d2l
```

Keep the generator, verifier models and axes identical to the other datasets, or provenance
stops being comparable across the corpus. They are recorded in each `.meta.json`; read one
before generating a new dataset.

After generating: re-ingest, re-run the offline audit (unique hints, no furniture), then
`evals/audit_golden.py` against the live backend.

## Re-baselining a threshold

Only after the dataset is clean. Lowering a threshold to make a run pass is how `paper` came
to carry the lowest floor in the repo (0.45/0.30) while being the only corrupt dataset.

State what the number was measured on — dataset, date, ingestion state — in the same commit.
A threshold with no provenance cannot be re-derived and will be lowered again.

## Fixing a contaminated corpus

**The defect belongs in the pipeline, never in a side script that cleans the data.** Luminary
ingests scraped web content as a first-class path, so anything wrong with a scraped corpus is
wrong in a real user's library too. Fix it in ingestion, then regenerate the golden.

Do not truncate a corpus to remove contamination without checking what is past the cut — on
`art_of_unix.txt` the apparent seam had 1105 words of real book prose after it, including a
Part heading.

## Generation quality: measured 2026-08-12, first time ever

`make eval` is retrieval only. `make eval-gen` runs the shipped answering path and asserts
faithfulness, answer relevance, citation support, answer rate and citation coverage. Before it
existed every generation column in the Quality UI read `-`, because nothing ever populated them.

| | book | paper |
|---|---|---|
| faithfulness (HHEM) | 0.678 | 0.626 |
| answer_relevance | 0.706 | 0.852 |
| **citation_support_rate** | **0.485** | **0.400** |
| citation_coverage | 0.750 | 0.872 |
| answer_rate | 0.900 | 0.975 |

**Under half the citations the product shows support the answer they sit under.** That is the
open defect, not a measurement artifact: 0 judge calls failed on either run. `make eval-gen`
fails on both datasets today and is supposed to.

`citation_support_rate`'s 0.80 floor predates this work and had never once fired.
`answer_rate` and `citation_coverage` are new floors with no historical baseline behind the
0.80 — treat them as provisional and set them deliberately rather than reading them as
established bars.

Two independent bugs had kept citation support at `None` for all 285 recorded runs, and each
would have hidden the other:

1. It paired claims by splitting prose on `[N]` markers. The product emits prose plus a JSON
   citations block and never inline markers, so zero pairs were ever built.
2. `judge_citation` imports `litellm`, which was not a dependency of the `evals` project, so
   every judge call raised `ModuleNotFoundError` and was swallowed into a failure counter.

Both surfaced only once I-32 made an uncomputed metric fail instead of pass.

## What is not covered today

Know the hole before quoting coverage. `make eval` runs `book` and `paper` only, retrieval
only, and `make ci` runs no eval at all. `DATA/study` holds PDFs that no golden covers, so the
PDF parse path is unmeasured by retrieval eval.
