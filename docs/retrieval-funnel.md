---
description: The three-layer retrieval funnel -- layer ownership, tuning knobs, and the eval workflow for changing them.
---

# Retrieval Funnel (L1 / L2 / L3)

Luminary's retrieval is a funnel. Each layer has one job and its own metrics; a
layer can only reorder or cut what the layer above hands it.

```
L1  candidate generation   vector (LanceDB) + BM25 (FTS5) + graph expansion -> RRF
L2  precision ranking      cross-encoder rerank over the top-`depth` RRF pool
L3  final re-ordering      (not built) MMR diversity, dedup, listwise polish
```

## Layer ownership

- **L1 (recall).** `HybridRetriever.retrieve` fans out to the legs and fuses
  with RRF (`rrf_merge`). Graph is not a separate ranked leg: it contributes by
  expanding the vector query with canonical entities/aliases (`_graph_expand`).
  L1's metric is HR@depth of the fused pool -- if the answer chunk is not in the
  pool, nothing downstream can recover it.
- **L2 (precision).** `_rerank_candidates` re-scores the top-`depth` RRF
  candidates with `cross-encoder/ms-marco-MiniLM-L-6-v2` and returns top-k,
  optionally cutting candidates below a score threshold. L2's metrics are
  MRR/nDCG at fixed k, and faithfulness downstream (junk cut = cleaner
  generation context).
- **L3 (composition).** Absent. `_diversify` (round-robin section/speaker
  breadth, skipped when reranking) and `_expand_context` (neighbour windows)
  are the current stand-ins; a real L3 would do MMR/dedup over the reranked
  list. Out of scope for the L2 branch.

## L2 knobs

| Knob | Default | Where |
|---|---|---|
| `rerank` on/off | ON (DB setting `rerank_enabled`) | user toggle, chat path |
| `RERANK_DEPTH` | 50 | `config.py`, env-overridable; per-request `rerank_depth` on `/search` (capped at 200) |
| `RERANK_SCORE_THRESHOLD` | None (off) | `config.py`; per-request `rerank_threshold` on `/search` |

Depth is the one L2 knob that can move HR@5: reranked HR@5 is bounded by
HR@depth of the RRF pool. Latency is linear in depth (~5ms/pair on CPU), so
depth changes are a measured trade, never a hunch. The threshold is a
precision/faithfulness lever only -- it can never add hits, and the top
candidate always survives so a strict cut degrades context rather than
emptying it.

## Tuning workflow

Every knob change goes through the eval harness, never straight to config:

Run from `backend/` (the runner needs its uv env) against the dev server
(`--backend-url http://localhost:7820`; the flag defaults to :8000):

```
# Depth sweep: adds one rrf+rerank@N ablation arm per depth.
uv run python ../evals/run_eval.py --backend-url http://localhost:7820 \
    --dataset book_time_machine --ablation --rerank-depths 25,50,100,200

# Threshold probe on the standard run:
uv run python ../evals/run_eval.py --backend-url http://localhost:7820 \
    --dataset book_time_machine --rerank --rerank-threshold 0.0
```

DB-generated datasets (Monitoring -> Evals) run the same way with
`--dataset-id <uuid>` instead of `--dataset`.

Reading a depth sweep: if HR@5 climbs with depth, the missing answers were in
L1's deeper ranks and L2 depth (or a better L1 fusion) recovers them; if it
plateaus while HR@5 stays below target, the answers are not in any leg's
candidates at all -- that is an L1 recall problem (chunking, embeddings, query
expansion) and no L2 tuning will fix it. Per the eval-integrity rule, sweeps
are document-agnostic: pick depths/thresholds on one dataset only if they hold
on the others too.

## Measured results (2026-07-09)

Depth sweep (25/50/100/200) and threshold probe (logit 0.0) over three
30-question datasets: `apache_iceberg_20250526_gpt5_4` (db), `d2l_gpt5.4`
(db), `book_time_machine` (file). HR@5 / MRR@5:

| arm | iceberg | d2l | time_machine |
|---|---|---|---|
| rrf (no rerank) | .633 / .480 | .700 / .523 | .633 / .419 |
| rrf+rerank@25 | .633 / .541 | .767 / .633 | .567 / .511 |
| rrf+rerank@50 (default) | .633 / .541 | .767 / .633 | .567 / .494 |
| rrf+rerank@100 | .633 / .541 | .767 / .633 | .567 / .494 |
| rrf+rerank@200 | .667 / .558 | .767 / .633 | .567 / .494 |
| @50 + threshold 0.0 | .600 / .530 | -- | .567 / .494 |

Decisions:

- **`RERANK_DEPTH` stays 50.** 50 -> 100 changes nothing on any dataset;
  200 recovers exactly one question on one dataset at 4x the latency.
  Depth 25 is metric-equivalent to 50 everywhere at half the latency --
  an acceptable cut if rerank latency ever matters.
- **`RERANK_SCORE_THRESHOLD` stays off.** Logit 0.0 cut a gold chunk on
  iceberg (HR@5 .633 -> .600) and did nothing elsewhere. The retrieval side
  can only be hurt by a cut; turn it on only if a generation-eval shows a
  faithfulness win that outweighs it.
- **The HR@5 ceiling is L1's, confirmed.** A pool probe (top-100 RRF, no
  rerank) shows the gold passage is absent from the pool entirely for 7/30
  iceberg and 3/30 d2l questions. The misses are dominated by short deictic
  follow-ups from the persona-diverse golden generator ("data masking?",
  "CTAS for what here?", "explain auditing here") -- queries with no lexical
  or semantic anchor to the gold passage. The lever is query expansion /
  context carrying (HyDE, coreference), not chunking and not L2.
- **Remaining L2 headroom is the model, not the knobs.** Iceberg and d2l
  each have 7 questions whose gold sits at ranks 6-46 -- inside the default
  depth-50 window -- yet the MiniLM cross-encoder lifts only some of them
  into the top 5, and on time_machine it nets *negative* HR@5 (.633 -> .567,
  gold demoted out of top-5) while still raising MRR. A stronger
  cross-encoder, or an L3 blend of RRF and CE scores that stops confident
  demotions, is the next precision lever.
