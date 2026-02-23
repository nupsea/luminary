# Luminary Evals

Evaluation scripts using RAGAS for measuring retrieval and generation quality.

## Structure

- `golden_datasets/` — curated QA pairs per content type
- `scripts/` — RAGAS evaluation runners

## Metrics

- HR@5 (Hit Rate at 5) — retrieval quality
- MRR (Mean Reciprocal Rank) — ranking quality
- Faithfulness — answer grounded in retrieved context
- Answer Relevancy — answer addresses the question
