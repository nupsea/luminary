# Luminary Eval Metrics — reference

Every number in the Quality dashboard, what computes it, what it means, and how to
read it. Design principle: **numbers are honest and unbiased**. Retrieval and
golden-quality metrics are purely structural (no LLM). The only LLM in the loop
is the *local* RAGAS judge for generation metrics (Ollama, per invariant I-16) and
the frontier model used **once** to author a golden — never to score a run.

---

## 1. Retrieval metrics (no LLM)

Both are computed by matching a golden question's **`context_hint`** — a verbatim
phrase from the source that contains the answer — against the text of the chunks
the retriever returns for that question. Matching is normalized: lowercase,
collapsed whitespace, straightened smart-quotes, hint truncated to its first 80
chars; a golden may carry several alternate hints and *any* one counts.

**Scope caveats (read before comparing to external benchmarks):**
- Retrieval is **within-document**: the eval passes the golden's `document_id`
  to `/search`, so these numbers measure "find the right chunk given the right
  document". Cross-corpus document routing is not exercised.
- Both metrics are computed over the **top-5 `/search` results only** — chunks
  cited by `/qa` never leak into HR@5/MRR, so retrieval numbers are comparable
  across retrieval, generation, and citation runs. MRR is therefore MRR@5.

### HR@5 — Hit Rate at 5
- **Computed:** fraction of questions where at least one hint appears in the text
  of **any of the top-5** retrieved chunks. `hits / total`.
- **Signifies:** *recall* — can the retriever surface a chunk that actually
  contains the answer, within the top 5 a user would see?
- **Interpret:** 0–1, higher is better. **Gate ≥ 0.50.** d2l sits at 0.84 (strong).
  HR@5 is capped below 1.0 if a golden has non-verbatim hints (see
  `hint_verbatim_rate` — those questions are unretrievable by construction).

### MRR — Mean Reciprocal Rank
- **Computed:** for each question, find the rank *r* (1-based) of the **first**
  retrieved chunk containing a hint; reciprocal rank = `1/r` (0 if none found).
  MRR = mean over all questions. Rank-1 → 1.0, rank-2 → 0.5, rank-5 → 0.2.
- **Signifies:** *ranking quality* — how **high** the answer sits. This is the
  metric that matters for a "show the best chunk first" experience.
- **Interpret:** 0–1, higher is better. **Gate ≥ 0.35.** Protect this: a change
  can lift HR@5 (recall) while lowering MRR (demoting a correct rank-1) — always
  read them together. Depth is pinned at 5 (MRR@5) even though samples now carry
  10 contexts for nDCG.

### nDCG@10 — normalized Discounted Cumulative Gain at 10
- **Computed:** each golden lists distinct relevant passages with grades
  (`relevance: [{hint, grade}]`; grade 2 = the passage the answer was authored
  from, grade 1 = another passage stating the same answer). Walking the top-10
  retrieved chunks, each passage is credited once at the first chunk containing
  it, discounted by `1/log2(rank+1)`; the sum is divided by the ideal ordering's
  score. Goldens without `relevance` fall back to `context_hint` as a single
  grade-1 passage — nDCG then behaves like a log-discounted MRR.
- **Signifies:** *whole-window quality* — how much relevant material reaches the
  k~6–10 chunk context handed to the LLM, and how high it sits. This is the
  A/B metric for the cross-encoder reranker: HR@5/MRR often miss it lifting the
  2nd and 3rd relevant passages into the window.
- **Interpret:** 0–1, higher is better. **Provisional bar ≥ 0.40, report-only**
  (not asserted) until graded goldens exist and baselines are recorded.

---

## 2. Strategy ablation

The ablation runs the same golden through each retrieval strategy so you can see
where quality comes from. Reported as HR@5 + MRR + nDCG@10 per strategy.

| Strategy | What it is |
|----------|-----------|
| `vector` | Dense bi-encoder (BAAI/bge-m3) cosine similarity. Semantic; robust to paraphrase. |
| `fts` | BM25 keyword search (SQLite FTS5), AND-first with OR backfill. Lexical; strong on exact terms, weaker on pure paraphrase than the dense arm. |
| `graph` | Vector search on a graph-expanded query (adds related entities). |
| `rrf` | **Reciprocal Rank Fusion** of vector + keyword — the shipped default. |
| `rrf+rerank` | RRF's top-50 re-scored by a cross-encoder (ms-marco-MiniLM), top-k kept — the shipped reranker path. |

**How to read it:** `rrf` should dominate `vector`/`fts` alone (fusion wins).
Compare `rrf` vs `rrf+rerank` to decide if the cross-encoder is worth ~250 ms/query.

An ablation run's pass/fail gate applies to the **shipped arm** (`rrf+rerank`,
falling back to `rrf`) — the same HR@5/MRR thresholds as a single run. The
shipped arm also feeds the dataset list and the headline cards, so a fresh
ablation updates the numbers you see everywhere.

> **Reranker in dev:** the cross-encoder fail-softs (returns RRF order unchanged)
> in a long-running `uvicorn --reload` backend after repeated reloads — a
> torch/tokenizers + reloader quirk, not a code bug. Measure the rerank A/B
> against a **restarted / fresh dev or production (`make start`) backend**, where
> it reorders correctly.

**FTS fixes (2026-07-01).** Two bugs had made standalone `fts` read ~0:
1. *Score polarity* — BM25 scores are **negative** (more-negative = more-relevant);
   the eval re-sorted results descending, inverting the ranking. Fixed: the eval
   now **preserves the backend's ranking** instead of re-sorting.
2. *Implicit AND* — FTS5 treats space-separated terms as an AND (every term must
   be in one chunk), so a full-sentence question matched nothing. Fixed:
   `keyword_search` runs the **precise AND first** and **backfills with an OR pass**
   (any term, BM25-ranked) when it under-fills k, keeping the exact AND hits on top.

After both fixes, `fts` recovers to **0.6–1.0 across every doc** (was 0 on several)
and sometimes beats `vector` (time_machine, paper) — a real contributor, not a dead
arm. It also resolves an apparent `graph == rrf` tie: with `graph_expand` on, RRF's
dense arm uses the graph-expanded query (= the `graph` strategy), and when `fts`
returned nothing RRF collapsed onto it; now that `fts` contributes, they diverge.

---

## 3. Generation metrics

All generation metrics score **real generated answers**: the eval calls
`POST /qa` per question (the app's default QA pipeline, or `--model` to override)
and scores *those* answers. The golden ground-truth answer is never scored —
judging the golden against retrieved context would self-grade the dataset and
trend to 100% by construction. Every generation run records `answer_model`
("app-default" or the override) so the UI can distinguish real generation scores
from legacy self-graded ones.

**Faithfulness uses a dedicated NLI model; the other metrics use a local judge.**
Faithfulness is deterministic and always runs when answers exist. Answer
relevance (and the optional context metrics) still use a **local Ollama judge**
(I-16); a frontier model is never used to score, and the judge is opt-in via
`--judge-model` (default empty).

Small local judges are noisy — rows that fail JSON decoding are dropped and the
score is the mean of successful rows. The run records `judge_failed_calls` /
`judge_total_calls` (and `qa_failed_calls` / `qa_total_calls` for unanswered
questions), and the Runs tab surfaces them instead of a silent n/a.

### Faithfulness
- **Computed:** a dedicated NLI consistency model (Vectara HHEM-2.1-Open by
  default, `FAITHFULNESS_MODEL` to swap) scores `premise = joined retrieved
  context` against `hypothesis = generated answer` → P(answer supported by
  context), averaged over answers. **No LLM judge** — deterministic, fully local,
  runs whenever real answers exist (independent of `--judge-model`). This is why
  faithfulness now reliably appears instead of dropping to n/a on judge flakiness.
  Weights are Apache-2.0, <600MB, CPU-friendly, cached under
  `$DATA_DIR/models/<slug>` on first run; provenance is recorded as
  `faithfulness_model` in `extra_metrics`. Loading uses `trust_remote_code=True`
  (Vectara's official repo). Measures grounding in the retrieved context, not
  world truth — a true-but-ungrounded claim scores low, which is correct.
- **Signifies:** hallucination-freeness — is the answer grounded, not invented?
- **Interpret:** 0–1. **Gate ≥ 0.65 is REPORT-ONLY** while HHEM is re-baselined —
  its distribution differs from the old RAGAS judge (a clearly-supported claim
  scores ~0.8, not ~1.0), so the gate must be re-derived from a labeled run before
  it enforces. Low with a high HR@5 = the generator is drifting from good context
  (a generation problem, not retrieval).

### Answer Relevance
- **Computed:** the judge generates questions the answer would answer and measures
  their embedding similarity to the original question.
- **Signifies:** does the answer actually address what was asked?
- **Interpret:** 0–1. **Gate ≥ 0.50.**

### Citation Support Rate
- **Computed:** parse `[N]`-style inline citations from the answer; fraction whose
  cited chunk actually supports the attached claim.
- **Signifies:** are citations real, not decorative?
- **Interpret:** 0–1. **Gate ≥ 0.80.** Only meaningful for the cited-chat path.

---

## 4. Golden-dataset quality (deterministic — unbiased)

Scored purely structurally (no LLM), so it cannot be biased by or toward any
model. Shown on the "Golden dataset" card.

| Metric | Computed | Signifies / interpret |
|--------|----------|----------------------|
| **hint_verbatim_rate** | fraction of hints that are a verbatim substring of the source | **Fairness guarantee.** A non-verbatim hint is unretrievable and unfairly lowers HR@5/MRR. Should be ~1.0; below that, the *golden* is at fault, not the retriever. |
| **self_contained_rate** | fraction of questions with no document-reference phrases ("the text", "this passage", …) | Questions test the *subject*, not reading comprehension of a document. |
| **answer_ok_rate** | fraction with a non-trivial answer (≥10 chars) | Guards against empty/degenerate answers. |
| **question_len_mean ± std** | word-count mean and spread | Realism proxy: low std = homogeneous, "system-generated" questions; healthy goldens vary (e.g. d2l ≈ 12.6 ± 6.6). |
| **distinct_personas** | count of reader-intent personas present | Coverage of how real users ask (newcomer / practitioner / decision-maker / deep-diver / skeptic). |
| **quality_score** | `0.5·verbatim + 0.25·self_contained + 0.25·answer_ok` | Composite, weighted toward retrievability (the fairness axis). ≥90% green, ≥75% amber. |

The Golden card shows **every composite component** (verbatim, self-contained,
answer_ok) so a high score can't hide a weak axis, plus a provenance badge:
**cross-verified** (has a `.meta.json` sidecar with verify models) vs
**legacy · unverified** (hand-authored before the verified pipeline — regenerate
to upgrade).

---

## 5. Topic-generation eval (no LLM)

Compares a document's generated study topics to a curated golden list.

- **Precision** = matched_predicted / predicted; **Recall** = matched_golden /
  golden; **F1** = harmonic mean. Matching is fuzzy on titles (exact, token-set
  Jaccard ≥ 0.6, or ≥2-token containment).
- **junk_rate** = fraction of predicted topics flagged as boilerplate/non-topics
  (index, copyright, bare numbers, …).
- **Interpret:** **F1 gate ≥ 0.70**, **junk_rate ≤ 0.15**. High junk_rate is the
  signal for the failure the SQL-Cookbook case exposed (sample-data leaking in).

---

## 6. Thresholds (quality gates)

`--assert-thresholds` fails the run if any is missed. Defaults are general, not
tuned to any document.

| Metric | Gate |
|--------|------|
| HR@5 | ≥ 0.50 |
| MRR | ≥ 0.35 |
| Faithfulness | ≥ 0.65 |
| Answer Relevance | ≥ 0.50 |
| Citation Support | ≥ 0.80 |
| Topic F1 | ≥ 0.70 |
| junk_rate | ≤ 0.15 |

---

## 7. How to read a result

1. **Golden-quality card first.** If `hint_verbatim_rate < 100%`, fix the golden
   before trusting HR/MRR — the numbers are unfair to the retriever otherwise.
2. **HR@5 + MRR together.** HR = "is the answer reachable"; MRR = "is it on top".
3. **Ablation** to attribute quality to a strategy and to judge the reranker per
   dataset — its effect is **dataset-dependent** (it rescues weak baselines and can
   hurt already-strong ones; e.g. time_machine MRR +0.14 but d2l MRR −0.10).
4. **Faithfulness / Answer Relevance** only when you ran with a judge; treat a
   single small-local-judge run as directional, not precise.
