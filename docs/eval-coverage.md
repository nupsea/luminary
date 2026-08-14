---
description: What the eval suite measures, what it does not, and which gate enforces each. The map to read before quoting any number.
---

# Eval coverage

What is measured, by which target, on which corpus. Read `docs/model-footprint-plan.md` for the
numbers themselves and the `eval-integrity` skill for the rules that keep them honest.

The pipeline has three stages, and a number from one says nothing about the others. Retrieval
scores what was indexed and cannot report what never arrived; generation scores answers over
whatever retrieval returned.

| Stage | Measured by | Corpus | Gated |
|---|---|---|---|
| Ingestion | `make eval-ingest` — retention, duplication | all 12 manifest documents | yes |
| Retrieval | `make eval` — HR@5, MRR, nDCG@10 | book, paper, legal, play, study | yes |
| Generation | `make eval-gen` — faithfulness, answer relevance, citation support, citation coverage, answer rate | book, paper | yes |
| Intent routing | `make eval-intent` — routing accuracy, per-route P/R | `golden/intents.jsonl`, 50 rows | yes |
| Topics | `make eval-topics` | d2l | yes |
| Summaries | `evals/run_summary_eval.py` | — | **no target** |
| Flashcards | `evals/run_flashcard_eval.py` | — | **no target** |
| Corpus routing | `evals/run_corpus_routing.py` | — | **no target** |
| HTTP contract | `make smoke` — ~230 scripts | live backend | yes, separately |

## What is not covered

- **Three eval runners still have no make target**: summary, flashcard, corpus routing. They
  exist, they import cleanly, and nothing runs them. Intent routing was the fourth and is now
  gated by `make eval-intent`, which matters most of the four: the chat graph routes every
  message by intent, so a misroute makes each downstream number describe a question the user did
  not ask (I-25, I-26).
- **`make eval-gen` covers 2 of 6 kinds.** All six have been measured once (see the plan doc), but
  only book and paper are wired into the target, so only they are re-measured on a change.
- **No end-to-end task-success measure.** `make smoke` checks wire contracts, not whether the
  product answered well.
- **The judge is unvalidated against human labels.** It scores its own notion of citation support
  consistently; nothing establishes that notion is right.
- **Enrichment, entity extraction and the graph are unmeasured.** `eval-ingest` stops at chunk
  retention.

## Reading a number without misleading yourself

**Intent routing is deterministic.** Measured 0.8800 on three consecutive runs, sd 0 — the
keyword heuristic answers most messages without an LLM and the classifier runs at temperature 0.
So a single run is a valid measurement here and a small delta is real, unlike generation. Weakest
route is `comparative` at 0.75 recall (precision 1.0000): comparative questions get routed
elsewhere rather than the reverse, and `search` precision 0.8000 suggests where they land.

**Generation metrics are noisy; retrieval metrics are not.** Retrieval is bit-reproducible on a
fixed corpus — the same corpus returns the same HR@5 to four decimal places. Generation is not:
measured over 4 runs of one frozen build, `citation_support_rate` has sd 0.052 on book and 0.025
on paper, so **a single run cannot resolve a change below ~0.10 (book) or ~0.05 (paper)**. Two
changes were once credited with moving it by less than that; both were noise. A/B anything
generation-side over repeated runs and compare distributions.

**Floors are collapse detectors, not quality bars.** Every generation floor is `mean - 3sd` of the
weaker dataset. Passing means no leg of the pipeline died. It does not mean the product is good,
and the number to beat is always the measured mean.

**Check the stage before attributing a change.** A retrieval regression can come from ingestion;
a generation regression can come from retrieval. `eval-ingest` first, then `eval`, then
`eval-gen` — in that order, because each is the ceiling on the next.

**`book` is the hardest dataset, not the typical one.** It scores lowest on citation support of
all six kinds. Tuning against it alone overfits to the worst case.
