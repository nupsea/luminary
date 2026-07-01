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
  read them together.

---

## 2. Strategy ablation

The ablation runs the same golden through each retrieval strategy so you can see
where quality comes from. Reported as HR@5 + MRR per strategy.

| Strategy | What it is |
|----------|-----------|
| `vector` | Dense bi-encoder (BAAI/bge-m3) cosine similarity. Semantic; robust to paraphrase. |
| `fts` | BM25 keyword search (SQLite FTS5). Lexical; strong on exact terms, **weak on casual/paraphrased questions**. |
| `graph` | Vector search on a graph-expanded query (adds related entities). |
| `rrf` | **Reciprocal Rank Fusion** of vector + keyword — the shipped default. |
| `rrf+rerank` | RRF's top-50 re-scored by a cross-encoder (ms-marco-MiniLM), top-k kept — the shipped reranker path. |

**How to read it:** `rrf` should dominate `vector`/`fts` alone (fusion wins).
Compare `rrf` vs `rrf+rerank` to decide if the cross-encoder is worth ~250 ms/query.

**Known gotcha (fixed 2026-07-01):** FTS relevance scores are raw BM25, which are
**negative (more-negative = more-relevant)**. The eval used to re-sort results
descending, silently inverting FTS's ranking and reporting ~0. It now preserves
the backend's ranking. Standalone `fts` is still low (~0.06 on d2l) — that's
**honest**: BM25 on casual/persona questions is genuinely weak, which is precisely
why hybrid RRF exists.

---

## 3. Generation metrics (RAGAS — local judge)

Only computed when you pick a Judge model (defaults to *None — fast*). The judge
is a **local Ollama model** (I-16); a frontier model is never used to score.
Small local judges are noisy — rows that fail JSON decoding are dropped and the
score is the mean of successful rows (a WARNING prints the failure %).

### Faithfulness
- **Computed:** the judge decomposes the generated answer into atomic claims and
  measures the fraction **supported by the retrieved context**.
- **Signifies:** hallucination-freeness — is the answer grounded, not invented?
- **Interpret:** 0–1. **Gate ≥ 0.65.** Low with a high HR@5 = the generator is
  drifting from good context (a generation problem, not retrieval).

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
