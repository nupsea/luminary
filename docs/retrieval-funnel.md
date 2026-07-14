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

## Query understanding & corpus routing (pre-L1)

Before the funnel ranks, a corpus-wide ("All documents") query is routed. These
steps are deterministic and local-first (no LLM) and apply to any corpus -- they
key off content-type strings and dated-entry structure, never a specific
document.

- **Spell correction** (`query_spellcorrect.py`). Out-of-vocabulary query tokens
  (length >= 4) are corrected to the nearest corpus token by Norvig
  edit-distance-1, frequency-ranked. A single mistyped proper noun otherwise
  collapses an exact-match BM25 query to the wrong document. `QUERY_SPELL_CORRECT`
  (default on); per-request `spell_correct=`.
- **Query filters** (`query_understanding.py::parse_query_filters`). Extracts a
  content-type set and a date window from natural language via keyword/regex
  rules (`content_types`, `date_from`, `date_to`). A journal-style request
  resolves to a content type (narrow to those documents) and a month window
  (keep only chunks written in it) instead of running semantic search over the
  raw phrase.
- **Content dates** (`content_dates.py`). At ingest each chunk gets an
  `entry_date` parsed from its own text and forward-filled -- but only for
  documents that look like dated-entry logs (a density gate: enough directly
  dated chunks, over a minimum fraction, across several distinct dates). This
  keeps a stray reference date in a book from smearing across every chunk.
- **Filtered retrieval.** `retrieve()` / `retrieve_with_images()` / `/search`
  take `date_from`/`date_to`; `_filter_by_entry_date` drops undated and
  out-of-range chunks after the RRF merge and again after context expansion (a
  neighbour window can cross a date boundary). The candidate pool is deepened
  when date-filtering so enough dated chunks survive the cut. In chat,
  `search_node` applies the parsed filters on unscoped queries, resolving
  content types to document IDs; when routing narrows to a doc set it widens `k`
  and skips the per-document cap so the target document can dominate.
- **Generative intent** (`intent.py`). A "write/generate/compose ... based on
  ..." request matches no question keyword, so the heuristic would fall to the
  low-confidence catch-all and defer to the LLM classifier -- which mislabels it
  and routes away from retrieval, so the grounding content is never fetched. A
  generative-verb rule classifies these at confidence >= 0.7 so they route
  straight to `search_node`. (Note: generation of the creative output itself is
  still extractive-QA style; a dedicated creative mode is future work.)

The unscoped routing regime is measured by `evals/run_corpus_routing.py`
(route@1 / route@5 / HR@5, with a `--typo` arm), persisted as
`eval_kind=corpus_routing` and shown in the Quality Runs tab.

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

Every `--ablation` run also reports **L1 pool recall** -- Recall@K of the raw
RRF pool (no rerank, no neighbour expansion; `--recall-depths`, default
`50,100,200`). This is the funnel's recall ceiling stated directly:
`recall@depth - reranked HR@5` is the precision loss chargeable to L2, and
`1 - recall@depth` is the true L1 gap no downstream layer can recover. The
arm uses `/search?expand_context=false` so the measured pool is exactly what
the cross-encoder would see at that depth.

DB-generated datasets (Monitoring -> Evals) run the same way with
`--dataset-id <uuid>` instead of `--dataset`.

Reading a depth sweep: if HR@5 climbs with depth, the missing answers were in
L1's deeper ranks and L2 depth (or a better L1 fusion) recovers them; if it
plateaus while HR@5 stays below target, the answers are not in any leg's
candidates at all -- that is an L1 recall problem (chunking, embeddings, query
expansion) and no L2 tuning will fix it. Per the eval-integrity rule, sweeps
are document-agnostic: pick depths/thresholds on one dataset only if they hold
on the others too.

## Measured results (2026-07-09, corrected same day)

Depth sweep (25/50/100/200), threshold probe (logit 0.0), and L1 pool recall
over three 30-question datasets: `apache_iceberg_20250526_gpt5_4` (db),
`d2l_gpt5.4` (db), `book_time_machine` (file). HR@5 / MRR@5:

| arm | iceberg | d2l | time_machine |
|---|---|---|---|
| rrf (no rerank) | .633 / .480 | .700 / .523 | .633 / .419 |
| rrf+rerank@25 | .633 / .541 | .767 / .633 | .567 / .511 |
| rrf+rerank@50 (default) | .633 / .541 | .767 / .633 | .567 / .494 |
| rrf+rerank@100 | .633 / .541 | .767 / .633 | .567 / .494 |
| rrf+rerank@200 | .667 / .558 | .767 / .633 | .567 / .494 |
| @50 + threshold 0.0 | .600 / .530 | -- | .567 / .494 |

L1 pool recall (raw RRF pool, no rerank, no expansion):

| | iceberg | d2l | time_machine |
|---|---|---|---|
| recall@50 | .867 | .900 | .867 |
| recall@100 | .967 | .933 | .867 |
| recall@200 | 1.000 | .933 | .900 |

Decisions:

- **`RERANK_DEPTH` stays 50.** 50 -> 100 changes nothing on any dataset;
  200 recovers exactly one question on one dataset at 4x the latency.
  Depth 25 is metric-equivalent to 50 everywhere at half the latency --
  an acceptable cut if rerank latency ever matters.
- **`RERANK_SCORE_THRESHOLD` stays off.** Logit 0.0 cut a gold chunk on
  iceberg (HR@5 .633 -> .600) and did nothing elsewhere. The retrieval side
  can only be hurt by a cut; turn it on only if a generation-eval shows a
  faithfulness win that outweighs it.
- **The bottleneck is L2 precision, not L1 recall.** L1 places the gold
  inside the default depth-50 window for 87-90% of questions (100% at depth
  200 on iceberg), yet reranked HR@5 lands at 57-77%. The 20-30 point gap
  between recall@50 and reranked HR@5 is the MiniLM cross-encoder failing to
  lift gold it was handed -- on time_machine it nets *negative* HR@5 versus
  raw RRF (.633 -> .567, gold demoted out of the top 5) while still raising
  MRR. The next quality lever is a stronger cross-encoder and/or an L3 blend
  of RRF and CE scores that stops confident demotions; L1 work (chunking,
  query expansion) can recover at most the last ~10%.
- An earlier same-day probe concluded the opposite ("misses are absent from
  the pool -- an L1 gap"). That measurement was wrong: without rerank the
  retriever silently truncated its legs to 50 candidates regardless of the
  requested limit, so the "top-100 pool" it inspected never existed. The
  truncation is fixed (pool floors at `k`), and the recall arm now measures
  the real pool.
