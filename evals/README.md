# Luminary Eval Harness

A RAG evaluation framework built alongside [Luminary](../README.md) — the local-first document learning app. The harness benchmarks hybrid retrieval and grounded generation quality against curated golden datasets.

If you're evaluating a RAG pipeline and want a reproducible, open benchmark loop, this is the entry point.

---

## What it measures

| Metric | What it tests |
|--------|--------------|
| **HR@5** (Hit Rate at 5) | Does the right chunk appear in the top 5 retrieved results? |
| **MRR** (Mean Reciprocal Rank) | How high does the right chunk rank? |
| **Faithfulness** (RAGAS) | Is the generated answer grounded in the retrieved context? |
| **Answer Relevance** (RAGAS) | Does the answer actually address the question? |
| **Citation Support Rate** | Do inline citations support the specific claims they're attached to? |

---

## Quick run

```bash
# Retrieval-only (no LLM required, fast)
uv run python run_eval.py --dataset book --backend-url http://localhost:7820

# With LLM-based generation scoring
uv run python run_eval.py --dataset book --model ollama/gemma4

# Assert quality gates (exits 1 on failure — useful in CI)
uv run python run_eval.py --dataset book --assert-thresholds

# Export a shareable HTML report
uv run python run_eval.py --dataset book --export-html report.html
```

Or via Make from the repo root:

```bash
make eval
```

---

## Golden datasets

Located in `evals/golden/`. Each `.jsonl` has one JSON object per line:

```json
{
  "question": "What did the narrator discover in the Time Machine?",
  "ground_truth_answer": "The narrator discovered ...",
  "source_file": "time_machine.txt",
  "context_hint": "chapter 4"
}
```

| Dataset | Source | Questions |
|---------|--------|-----------|
| `book` | The Time Machine (H.G. Wells) | 30 |
| `alice` | Alice in Wonderland | 20 |
| `odyssey` | The Odyssey (Butler translation) | 20 |

Documents are auto-ingested on first run and their IDs cached in `evals/golden/manifest.json`. Re-runs skip ingestion.

---

## Thresholds

Luminary's CI uses per-dataset thresholds (defined in `evals/lib/`):

| Metric | Default threshold |
|--------|-----------------|
| HR@5 | ≥ 0.60 |
| MRR | ≥ 0.45 |
| Faithfulness | ≥ 0.65 |
| Answer Relevance | ≥ 0.50 |
| Citation Support Rate | ≥ 0.70 |

---

## Retrieval strategy

Luminary uses **RRF hybrid retrieval**: vector search (BAAI/bge-m3, 1024-dim ONNX) + BM25 keyword search + knowledge graph traversal, fused with Reciprocal Rank Fusion.

The `--ablation` flag benchmarks each strategy independently:

```bash
uv run python run_eval.py --dataset book --ablation
```

Output shows HR@5 and MRR for `vector`, `fts`, `graph`, and `rrf` side by side.

---

## Advanced options

| Flag | Default | Description |
|------|---------|-------------|
| `--dataset` | — | Golden dataset name (required, one of: `book`, `alice`, `odyssey`) |
| `--backend-url` | `http://localhost:8000` | Luminary backend URL |
| `--model` | — | LiteLLM model string for QA generation |
| `--judge-model` | settings default | LiteLLM model for RAGAS scoring |
| `--max-questions N` | all | Sample N questions (deterministic, seed=42) for fast runs |
| `--assert-thresholds` | false | Exit 1 if any threshold violated |
| `--export-html PATH` | — | Write a self-contained HTML report |
| `--check-citations` | false | Judge whether inline citations support their claims |
| `--hyde` | false | Enable HyDE-style query expansion |
| `--rerank` | false | Enable cross-encoder reranking |
| `--ablation` | false | Compare vector / fts / graph / rrf strategies |

---

## LLM tracing (optional)

Set `PHOENIX_ENABLED=true` in `backend/.env`. Arize Phoenix runs at **http://localhost:6006** and traces every LLM call — useful for debugging faithfulness failures.

---

## Scores history

Each run appends to `evals/scores_history.jsonl`:

```json
{"dataset": "book", "model": "ollama/gemma4", "hr5": 0.73, "mrr": 0.61, "faithfulness": 0.81, ...}
```

Use this to track regression across model or retrieval changes.

---

## Built with

- [RAGAS](https://docs.ragas.io/) — faithfulness, answer relevance, context precision/recall metrics
- [LiteLLM](https://litellm.ai/) — provider-agnostic LLM interface
- [Arize Phoenix](https://phoenix.arize.com/) — LLM observability (optional)
- Luminary's hybrid RRF retrieval — the pipeline being evaluated
