# Eval Runbook — generating and running Luminary's metrics

The eval harness is a **full-mode** feature (surface `quality_dashboard`, route
`/quality`, plus the `dataset_generator` service). It is off in public builds and
always on in full mode (`make luminary`).

All commands run from the repo root. The backend must be running on
`http://localhost:7820` for anything that searches or ingests.

---

## 0. Prerequisites

- Backend up: `make start` (prod) or `make dev`.
- For golden **generation** only: `OPENAI_API_KEY` in `backend/.env` and Ollama
  running locally (used for cross-model verification). Generation is the *only*
  step that calls a frontier model.
- Running the metrics needs **no** frontier model — retrieval uses `/search`
  (no LLM); the optional RAGAS judge uses local Ollama.

---

## 1. (One-time) Generate the golden Q&A

The golden is a committed artifact (`evals/golden/d2l.jsonl`). You only
regenerate it when you deliberately want a new set — never per eval run.

```bash
make golden-d2l
# or, for any other document:
uv run --project backend python evals/generate_golden.py \
  --source PATH/TO/document.md --out evals/golden/NAME.jsonl \
  --generator-model openai/gpt-5.4 \
  --verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
  --verify-axes answerable answer_correct --target 50
```

Output: `evals/golden/NAME.jsonl` (verified pairs, persona-tagged) and
`evals/golden/NAME.flagged.jsonl` (rejects + per-judge verdicts, for review).

## 2. Ingest the corpus

Retrieval/topic metrics need the document indexed in the backend. The runners
auto-ingest on first use and cache the doc id in `evals/golden/manifest.json`,
so this usually happens automatically. To do it explicitly, drop the file in the
library or let `make eval-d2l` ingest it on first run.

## 3. Run the metrics

| What | Command | Metrics |
|------|---------|---------|
| Retrieval | `make eval-d2l` | **HR@5**, **MRR** |
| Retrieval + reranker (A/B) | `make eval-d2l-rerank` | HR@5, MRR with cross-encoder |
| Topic generation | `make eval-topics` | topic precision/recall/**F1**, **junk_rate** |
| Generation (RAGAS) | `… run_eval.py --dataset d2l --judge-model ollama/qwen2.5:14b-instruct` | faithfulness, answer-relevance |
| Retrieval ablation | `… run_eval.py --dataset d2l --ablation` | HR@5/MRR per strategy (vector/fts/graph/rrf/rrf+rerank) |

Direct invocations (what the Make targets wrap):

```bash
# HR@5 / MRR (retrieval-only, no LLM)
cd evals && uv run --no-sync python run_eval.py --dataset d2l \
  --backend-url http://localhost:7820 --assert-thresholds

# Cross-encoder reranker A/B — run both and compare.
# NOTE: the reranker fail-softs (returns RRF order) in a long-running
# `uvicorn --reload` dev backend; run this against a fresh/restarted dev or a
# production (`make start`) backend, or the A/B will read as a no-op.
cd evals && uv run --no-sync python run_eval.py --dataset d2l --rerank
cd evals && uv run --no-sync python run_eval.py --dataset d2l --ablation

# Topic generation quality (backend venv — imports topic_service)
uv run --project backend python evals/run_topic_eval.py --dataset d2l \
  --backend-url http://localhost:7820 --assert-thresholds
```

## 4. Where results show up

Every run appends to `evals/scores_history.jsonl` **and** POSTs to the backend
store. They appear in the **Quality dashboard** (`/quality`, full mode):

- **Runs** tab — one row per run with HR@5, MRR, Faith, Routing, **Topic F1**,
  **Junk** (topic metrics ride in the generic `extra_metrics` column, so new
  metric families surface without a schema change). Filter by kind (`retrieval`,
  `topic`, `generation`, …).
- **Results** / **Ablations** / **Regressions** tabs — latest-per-dataset,
  strategy ablation, and regression deltas.

## 5. Thresholds (quality gates)

`--assert-thresholds` exits non-zero if a gate is missed:

| Metric | Gate |
|--------|------|
| HR@5 | ≥ 0.50 |
| MRR | ≥ 0.35 |
| Faithfulness | ≥ 0.65 |
| Topic F1 | ≥ 0.70 |
| Junk rate | ≤ 0.15 |

Thresholds are general defaults, not tuned to any one document.
