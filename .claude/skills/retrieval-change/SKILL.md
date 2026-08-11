---
name: retrieval-change
description: How to change retrieval in this repo and prove it did not regress — HybridRetriever, RRF fusion weights, the cross-encoder reranker, query expansion, chunking. Use whenever touching retriever.py, retriever_strategies.py, the FTS5 query path, or anything that changes what comes back from search.
---

# Changing retrieval

Retrieval quality is measured, not asserted. `pytest` proves the code runs; it does not prove
the results got better, and a change that improves one query class routinely degrades another.
**A green suite is not evidence for a retrieval change.**

## Measure before you change

Get a baseline first — a number produced after the change has nothing to compare against.

```
make eval          # book + paper datasets, asserts thresholds
make eval-d2l      # technical corpus, HR@5 / MRR, no judge — fast
```

Both need a backend running on :7820 with the corpus ingested. Record the numbers before you
touch anything.

## The metrics

- **HR@5** — was a relevant chunk in the top 5. Recall-shaped.
- **MRR** — how high the first relevant chunk ranked. Ordering-shaped.

A change can lift HR@5 while dropping MRR: it found more, ranked it worse. Report both. Never
report a single blended number.

Thresholds live in `THRESHOLDS` and `DATASET_THRESHOLDS` in `evals/run_eval.py` and vary by
dataset. Read them there — do not carry a remembered number into a decision. `--assert-thresholds`
makes the run exit non-zero below the floor.

The floors are **collapse detectors, not quality bars**. Clearing them says a leg of the funnel
is not dead. It does not say the change was an improvement — that is the delta against your own
baseline, on the same dataset, same day.

## A/B the reranker separately

`make eval-d2l` and `make eval-d2l-rerank` are the same dataset with the cross-encoder off and
on. Retrieval changes and reranker changes have to be attributed separately or you cannot tell
which one moved the number.

## Known shape of this funnel

- The bottleneck has measured as the MiniLM cross-encoder, not L1 recall. Widening candidate
  depth to fix a quality complaint usually buys nothing and costs latency.
- **FTS5 `MATCH` is implicit-AND across tokens.** Appending tokens absent from the corpus
  collapses BM25 recall to zero. Route query expansion to dense vector search only; keep keyword
  search on the original query. HyDE-style expansion is the exception — it is generated to look
  like source text, so it shares corpus vocabulary and can flow to both.
- **BM25 scores are negative** (more negative = more relevant). Never re-sort FTS results by
  `relevance_score` downstream; a descending sort silently inverts the ranking. Preserve the
  order the query returned.
- **`/search` matches carry `global_rank`.** Clients sort by it, never by `relevance_score`.
- Generation faithfulness (HHEM) is a **within-model** signal. Cross-model HHEM deltas are a
  style artifact and must never gate a model decision.

## Before finishing

- Numbers for both configurations, both metrics, against your own pre-change baseline.
- `make ci`.
- If the change alters a response shape, the `add-endpoint` skill applies too.
- If a number moved for a reason that was not predictable from the code, that is an invariant —
  use `invariant-capture`.
