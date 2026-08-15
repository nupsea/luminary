---
description: The single plan for model footprint, scheduling, substitutability, and the eval baseline that gates the switch. Six stages. Delete when the last one ships.
---

# Model switch and eval baseline

Four problems arrived as one user report on 0.5.0 ("uses a lot of memory, my Mac Air crashed
loading a PDF, ~16GB") and three independent eval audits. They have different causes, different
fixes, and one dependency: **nothing about the model can be decided until the measurement is
trustworthy.**

| | Problem | Cause | Stage |
|---|---|---|---|
| Memory | ~15.3GB peak on a 16GB host | Bundle never caps resident model count | 1 |
| Measurement | No number survives being compared across a change | Runs record nothing about what produced them; one run is not a measurement; part of the suite is invalid or ungated | 2, 3 |
| Adaptability | Better models do not move eval numbers | Prompts, parsers and budgets tuned to llama3.2; no metric sees the difference | 3, 4, 5 |
| Latency | An Ask queues behind ingestion | Background LLM work has no scheduling priority | 5 |

Runtime findings baselined against `ba0c1db` (0.6.1); eval findings against `39e6bf1`. Estimates
are marked as such — Stage 1 replaces the footprint estimates with measurements.

## What 0.6.1 already fixed

Do not re-solve these.

- `1195f4f` — `DocumentParser.parse` moved into `asyncio.to_thread`. Event-loop freeze on a 23MB
  PDF: 44.9s → 3.96s. In public mode the backend also serves the SPA, so that freeze stopped lazy
  route chunks arriving and the UI could not navigate.
- `1195f4f` — `OLLAMA_NUM_PARALLEL` sized from physical RAM by every install path including
  `supervisor.rs`, which passes the same value to Ollama and the backend so they cannot disagree.
  **Copy this mechanism for `OLLAMA_MAX_LOADED_MODELS`; it was the one variable left out of it.**
- `49c8806` — section summaries deferred behind `stage='complete'`. Large book to readable:
  17min → 86s. Per-unit cap now shrinks as a document grows.

0.6.1 moved the heavy work off the critical path. It did not make it cheaper: deferred summaries
and enrichment still issue LLM calls into the slots an Ask needs.

## Stages

Order is: **stop the crash, make numbers comparable, make the model visible, extract the seams,
schedule and calibrate, then swap.** Last time the swap came first, which is why there was
nothing to see it with.

| Stage | Contains | Exit gate |
|---|---|---|
| 1. Stop the crash | P0, P1 | Footprint baseline reproduces the ~16GB peak; post-fix delta measured; `make ci`, `make smoke` |
| 2. Make numbers comparable | E5, E4, E3, E6 | Two runs from different library states are visibly non-comparable; a frozen build reproduces its mean within its own sd |
| 3. Make the model visible | P2, E2, E9, E11 | Repair counters non-zero on llama3.2; scoped and unscoped arms both baselined; flashcard and routing targets in the gate |
| 4. Extract the seams | P3, P4, E7, E8 | No service reads `LITELLM_*`; rendered-prompt snapshots exist; holdout recorded and never used to select |
| 5. Schedule and calibrate | P5, P6 | TTFT under ingest load per profile; the matrix separates `qwen3.5:0.8b` from `4b` |
| 6. Switch and lean out | P7, P8, E10 | All three gates on all three profiles; both ratchets below `ba0c1db` |

`P` items are the model/runtime track and keep the phase numbers work has already been branched
under. `E` items are the eval substrate, numbered from the audit consolidation. A stage may not
start before its predecessor's exit gate, except Stage 1, which ships alone and blocks nothing.

---

## Stage 1 — Stop the crash

Ships alone as a patch release. **No answer changes, so no re-evaluation** — this is why it does
not wait for Stage 2.

### P0 — Measurement harness

`scripts/mem_profile.py`. Samples backend RSS, each Ollama runner via `/api/ps`, and system memory
**per ingestion stage rather than at steady state**, plus a latency probe issuing an Ask during
ingest and recording time to first token. Baseline commits as JSONL beside
`evals/scores_history.jsonl`.

Verified by: re-runs agree within ~10% on the same machine, and the baseline reproduces the
reported ~16GB peak on a 16GB host.

**Measured 2026-08-14** on a 36GB host, `OLLAMA_MAX_LOADED_MODELS` unset, backend 0.6.1, library
51 → 52 documents / 71,864 → 207,047 chunks. Rows in `evals/mem_profile_history.jsonl`; source is
a 43MB PDF that produced 135,183 chunks and took 2,412s to `stage=complete`.

| Arm | Peak backend + Ollama | Backend alone | Ask TTFT |
|---|---|---|---|
| idle | 13,026MB | — | 0.56 – 0.64s |
| ingest | **14,619MB** (at `entity_extract`) | 4,726MB | 79.8s, 115.6s |
| library Ask under that ingest | 13,950MB | 4,138MB | 1.3s, 75.0s, 92.6s |
| after `complete`, enrichment running | 11,166MB | 806MB | 114.3s |

Peak is `entity_extract`, not enrichment, and ~10GB of every figure is one resident
`qwen2.5:14b-instruct` left over from eval work — D1 with a number on it. **Interactive latency
under ingest load is 75–115s against 0.6s idle**, not the 10–20s this plan estimated from I-31's
throughput table; P5 is the user-visible half of the problem, not an optimisation after residency.

Not measured: the 16GB single-runner regime the crash came from. This host has 36GB and no
residency cap, so it is a different regime and the ~16GB peak claim stands unreproduced.

Falsifier: if peak is not dominated by the two Ollama runners, the diagnosis is wrong and P1 must
be re-derived. Check `_VECTOR_RENDER_DPI=150` with `_MAX_DIM=4000` (`image_extractor.py`) — a
4000×4000 RGB pixmap is ~48MB and up to 4 are taken per page — and the enrichment worker for a
leak.

A second contention channel is unmeasured and belongs in the same probe: embedding and reranking
are CPU-bound through `run_in_executor(None, …)` (`ingestion_nodes/embed.py:60`), so a large
ingest slows the query embed and the ~510ms cross-encoder even when nothing is queued behind the
LLM. Residency does not touch this.

Two product defects the probe found, both open:

- **An Ask over the library returns an empty stream under load.** 8 of 15 probes ended with no
  token; manual calls under the same load answered normally, so it is intermittent rather than a
  probe artifact. The probe now records whether a `done` event ever arrived and what the last
  event was, which is what separates a slow answer from a stream that closes on the user with no
  answer and no error.
- **An Ask scoped to a document still being ingested answers `{"error": "no_context"}`
  immediately**, without reaching the model. That is a readiness signal, not latency, and it is
  why probes default to library scope (`--probe-scope`).

### P1 — Residency and lifecycle

1. `supervisor.rs`: set `OLLAMA_MAX_LOADED_MODELS` alongside `OLLAMA_NUM_PARALLEL`, sized from
   `total_memory_gb()` — 1 under 24GB, 2 above. **Done.**
2. Vision calls pass `VISION_KEEP_ALIVE` (60s) so the runner releases when enrichment drains
   instead of holding ~6.5GB for the global 30m. **Done.**
3. `NER_MODEL` becomes a setting, replacing the model id hardcoded in three places. **Done** —
   `scripts/ner_compare.py` compares two entity models on the live corpus.

Verified by: P0 before/after; `make ci`; `make smoke`; a test asserting the bundle passes
`MAX_LOADED`.

#### The entity model cannot be unloaded

`retriever_strategies.py` skips `graph_expand` whenever `EntityExtractor._model is None`,
returning the query unexpanded:

```
if extractor._model is None:
    logger.info("graph_expand: GLiNER model not loaded yet; skipping expansion")
    return query
```

The guard is deliberate — it refuses to pay a 1.1GB load inside a search — but it means deferring
the model at boot, or reaping it after idle, **silently changes retrieval** rather than only
freeing memory. Both were the original items 3 and 4 of this phase; both are withdrawn.

The lever is a smaller model that stays resident, not a large one that does not. The current
default is `gliner_multi-v2.1` fine-tuned onto a synthetic PII dataset across six languages, while
`ENTITY_TYPES` asks for PERSON, ORGANIZATION, PLACE, CONCEPT, EVENT, TECHNOLOGY, DATE, LIBRARY,
DESIGN_PATTERN, ALGORITHM, DATA_STRUCTURE, PROTOCOL, API_ENDPOINT — none of them PII, and the
corpus is English. `gliner_small-v2.1` is 336MB against 1126MB.

Decide it in two steps, in this order:

1. `make ner-compare` — agreement, yield, type distribution, resident cost. Reports disagreements
   to read, not a score: neither model is ground truth.
2. `make eval` under each `NER_MODEL`, comparing hit_rate/MRR. **This is the gate.** Entities exist
   to serve retrieval, so retrieval is what must not regress.

If the small model holds retrieval, it becomes the default everywhere rather than only on small
machines — the size win is then incidental to using a model that matches the label vocabulary. If
it does not, the entity model stays large and resident, and its memory comes out of Stage 6's role
collapse instead.

**This decision now depends on Stage 2.** A `make eval` comparison across two `NER_MODEL` values
is exactly the comparison E5 says is currently unrecordable: re-ingesting one document has moved
an untouched document's MRR by the same magnitude as an entity-model change. Run the comparison
in one library state, or run it after E5 and record the fingerprint.

---

## Stage 2 — Make numbers comparable

Nothing downstream can be trusted before this. These four items change no product behaviour; they
change what a number means.

### E5 — A run does not record what produced it

`append_history` writes dataset, model, kind, metrics and `passed`
(`evals/lib/scoring_history.py:26`); `store_results` posts the same shape. Retrieval rows record
`model: "no-llm"`. Nothing records the embedder, the reranker id, the answering model the backend
actually used, the judge, or the state of the library.

That last one is not hypothetical. Re-ingesting `paper` moved `book`'s MRR from 0.4104 to 0.3979
with nothing about `book` touched, both values bit-reproducible on either side — the same
magnitude as the entity-model difference being measured at the time, which made that difference
indistinguishable from a library-state change.

The coupling is not universal and its mechanism is **not established**: ingesting three further
documents (~4,870 chunks) moved `book` and `paper` by zero. Two candidates sit in the code and
neither has been isolated — `bm25(chunks_fts)` scores over the whole FTS table with the
`document_id` filter applied to matched rows (`retriever.py:225`), and graph expansion reads an
entity graph that every ingest rewrites.

**Shipped 2026-08-14.** `GET /evals/environment` (`services/eval_environment.py`) reports the
build, the resolved models and the corpus fingerprint; `evals/lib/environment.py` captures it with
the eval git sha and the run's own flags; every gated runner stores it. Models resolve through
`get_effective_routing`, which is what the backend would actually call — the first version read
`llm_mode` and recorded `gpt-5-mini` for a `private`-mode backend that answers locally.

**Fix**: an environment block per run, persisted in the history row and in `/evals/store`.

| Field | Source | Why |
|---|---|---|
| Eval git sha, backend version | git, `/health` | Metric definitions change |
| Embedder id and dimension | config, I-9 | Changing it is a re-embed, not a swap |
| `RERANK_MODEL`, rerank on/off, strategy | config, run flags | Partially recorded already (`rerank`) |
| Chat / generation / judge ids **as resolved** | backend, not the CLI flag | Two of five call sites bypass the settings service today |
| Library fingerprint: documents, per-document chunk counts | DB | A corpus change re-ranks untouched documents |
| Run-group id, run index of N | E4 | A single generation run is not a measurement |
| Scoped / unscoped arm | E2 | Two regimes, not one number |

Two runs whose fingerprints differ are reported as non-comparable, never averaged.

Verified by: two runs from different library states are visibly non-comparable in
`scores_history.jsonl` without reading a commit log.

### E4 — No variance protocol in the harness

Generation metrics carry sd 0.052 (`book`) and 0.025 (`paper`) across four runs of one frozen
build, so a single run cannot resolve a change below ~0.10 / ~0.05. The number is documented in
`run_eval.py` and `eval-coverage.md`; the tooling to act on it does not exist — no repeat flag, no
run-group key, nothing comparing distributions.

**Shipped 2026-08-14.** `make eval-variance DATASET= RUNS= [COMPARE=<run_group>]` →
`evals/run_variance.py`. Runs the eval N times in separate processes — how the committed variance
figures were taken — sharing one `run_group`, aggregates from the rows the runs themselves wrote,
and gates on the **mean** rather than on any single run. `COMPARE=` reports each delta against the
noisier of the two series' sd and prints `inside noise` below 2sd. Three refusals rather than an
average: a series whose runs measured different systems (`same_conditions`), a comparison across
different systems, and a series with a missing run. `hit_rate_5`/`mrr`/`ndcg_10` moving inside one
series is reported as a corpus or funnel change, since they are bit-reproducible on a fixed corpus.

**Fix**: `--runs N` against one library state, each run recorded individually under a shared
run-group id with mean and sd; a comparison mode reporting the delta against recorded sd rather
than against a point.

Verified by: a frozen build reproduces its committed mean within its own sd, and a deliberate
no-op change reports "inside noise".

### E3 — The summary metric is invalid as written

`run_summary_eval.py:38-42` reads the source with `path.read_text(errors="ignore")[:8000]` and
hands it to `judge_hallucination_counts` (`:117`). Two independent failures in one line:

- **8,000 characters is ~1,500 words.** Every claim a summary draws from later in a book is judged
  against text the judge cannot see, so `no_hallucination` penalises correct summaries.
- **Raw bytes, not the ingested text.** The `eval-integrity` rule is explicit: read the corpus
  through `app.services.universal_parser.read_document_text`. On a PDF, `read_text` returns
  `%PDF-1.5 /FlateDecode`. `backend/tests/test_golden_integrity.py:89` already does this
  correctly; the summary runner does not.

The runner has no make target, which is the only reason this number has never been spent on a
decision.

**Shipped 2026-08-15.** Grounding is retrieved per claim (`/search` scoped to the document,
3 chunks per claim, 12k chars) instead of read off the front of the file, which is the only shape
that scales — the manual indexes 135k chunks. The judge scores that grounding, and
`summary_grounding` (HHEM over the same passages) is computed alongside it, so a machine with no
model to spare still gets an honest summary number. `make eval-summary` exists; floors stay unset
until a distribution is measured.

**What the fixed metric found immediately**: `/summarize/{doc}?mode=one_sentence` on
`ollama/qwen2.5:14b-instruct` returns 2,271 characters of conversational recap of two chapters —
"It seems like you've provided an excellent summary of the key events in Chapters XI and XII" —
against a prompt reading "Summarize in a single sentence of at most 30 words"
(`summarizer.py:47`). theme_coverage 0.333, conciseness 3.8x target, grounding 0.090. This is the
M4 thesis with a measurement under it, and it was invisible while the metric was invalid.

**Fix**: read through `read_document_text`; judge claims against the document rather than a prefix
— claim-level NLI over its chunks is cheaper, deterministic, and already exists in
`evals/lib/runners.py`. Then `make eval-summary`, a baseline, and a floor derived from measured
variance.

Verified by: a PDF row scores non-zero theme coverage, and a claim from the last chapter of `book`
is not counted as a hallucination.

### E6 — Hint matching is coupled to chunking

A hit is the hint normalised and truncated to 80 characters (`evals/lib/retrieval_metrics.py:30`),
substring-matched against a retrieved chunk.

- **A chunk boundary inside that window scores a miss** even when both halves are returned at ranks
  1 and 2. Any chunking change therefore moves HR@5 for a reason that is not retrieval quality.
- **The offline guard and the runtime metric normalise differently.**
  `test_golden_integrity.py:89` applies `html.unescape` and `\xa0` folding before `_norm`;
  `retrieval_metrics._norm` does not. A hint that passes the integrity test can be unmatchable at
  runtime on content carrying entities or non-breaking spaces.

**Shipped 2026-08-15.** `retrieval_metrics._norm` now unescapes entities and folds `\xa0`, and
`test_golden_integrity` uses that one function instead of its own copy. `count_boundary_misses`
reports misses whose hint reassembles across adjacent retrieved chunks, joined both with and
without a space — a whitespace-splitting chunker and the character-splitter fallback break
differently. **HR@5's definition is unchanged**: widening it would move every committed baseline
without retrieval changing, so the counter sits beside the metric as the evidence that a chunking
change moved a score.

**Fix**: one shared normaliser for both paths; match against adjacent retrieved chunks joined in
rank order, and record a `boundary_miss` count alongside HR@5 so a split reads as a split rather
than as a retrieval failure.

Verified by: a hint deliberately straddling a chunk boundary scores as a hit with `boundary_miss`
incremented, and the two normalisers are the same function.

---

## Stage 3 — Make the model visible

Stage 2 makes a number comparable. This stage makes it **sensitive to the thing being changed**.

### P2 — Output instrumentation — **shipped 2026-08-15**

- `parse_llm_json_*` returns `repairs: frozenset[str]` — `fenced`, `bad_escape`, `truncated`,
  `key_alias` — set as attributes on the existing `trace_llm_call` span.
- Collapse the duplicate parser ladder in `flashcard_parsers.py` into `llm_json.py`. One
  implementation.
- Counters for first-pass acceptance rate, retries per generation, requested-versus-delivered
  count.
- Time to first token recorded separately for interactive and background calls.

`app/services/llm_output_stats.py` holds process-wide monotonic counters; `llm_json` records
`fenced`, `bad_escape`, `truncated` and `surrounded_by_prose` per parse plus first-pass acceptance;
`card_field` records `key_alias`; `_collect_with_backfill` records requested/delivered/attempts.
`flashcard_parsers._parse_llm_response` now calls `llm_json` instead of re-implementing the ladder,
which both removes the duplicate and makes flashcard repairs visible. `GET /evals/output-stats`
exposes the snapshot and `run_eval` records the delta per run — no reset endpoint, because a diff
cannot be lost by a concurrent reader the way a reset can.

**First reading, `qwen2.5:14b-instruct`, 3 cards requested and 3 delivered**: `parses: 1`,
`parses_repaired: 1`, `repair_surrounded_by_prose: 1`, `first_pass_rate: 0.0`. The model wrapped
its array in prose and the parser carried it — invisible before this, because the cards came out
identical either way. That is the P2 acceptance criterion met: a non-zero repair count on the
shipped path.

Behaviour-neutral, a few dozen lines, and everything downstream argues from the numbers it
produces.

Verified by: `make ci`, plus a test that a known-bad completion yields the expected repair set. On
llama3.2 the repair counters must read **non-zero** — the parsers demonstrably exist for a reason,
so a zero reading means the instrumentation is wrong.

Falsifier: if repair rates really are near-zero in production, the tolerant parsers are dead weight
rather than a laundering channel. That is also a useful finding — delete them in P8 rather than
build around them.

#### Why this is the load-bearing item

Four mechanisms, all present in the tree, each of which independently flattens the difference
between a weak model and a strong one. They are why the last model comparison returned no signal.

| | Mechanism |
|---|---|
| M1 | `hit_rate_5`, `mrr` and `ndcg_10` are functions of bge-small and the L-12 cross-encoder. They contain **no generation-model term** |
| M2 | Two tolerant-JSON implementations plus `card_field` alternate keys make clean JSON and fenced, mis-keyed, truncated JSON produce **byte-identical downstream objects**. Nothing counts the repairs |
| M3 | `card_rejection_reason` plus retry-to-backfill guarantees N cards. A weaker model retries more: same quality number, different call count |
| M4 | `QA_CONTEXT_TOKEN_BUDGET = 1500` on a 256K-context model makes its advantage structurally unreachable; `FLASHCARD_USER_TMPL` carries a hardcoded worked example a strong model regresses toward |

M1 is why retrieval metrics are excluded from the model matrix. M2 and M3 are closed by P2. M4 is
closed by P4.

### E2 — Every gated arm runs scoped

`make eval` pins `source_document_id` per row, which `search_chunks` turns into `document_id` +
`limit=20` (`run_eval.py:265`). That measures ranking *within* the correct document. Real "All
documents" chat has no such pin, and `run_corpus_routing.py` exists because routing fails
differently — one mistyped proper noun collapses a query into the wrong corpus. It has no make
target.

**The stated reason not to run unscoped is stale.** The function warns that unscoped calls flatten
`/search`'s per-document groups without restoring rank order (`:274`), then sorts `all_matches` by
`global_rank` at `:319`, which is that restoration.

**Shipped 2026-08-15.** The stale warning is gone, `run_eval.py --unscoped` drops the pin for the
retrieval call while keeping it for `/qa` (scope must match the filter or the classifier routes to
library-wide synthesis), and `make eval-routing` records routing. Measured in one library state
(52 documents, 207,047 chunks — the 43MB manual is 65% of it):

| dataset | scoped HR@5 | unscoped HR@5 | route@1 | route@5 |
|---|---|---|---|---|
| book | 0.5250 | 0.5000 | 0.70 | 0.85 |
| paper | 0.8500 | **0.5500** | 0.75 | 0.80 |
| legal | 0.5500 | 0.5167 | 0.93 | 0.97 |
| play | — | — | 0.92 | 0.93 |
| study | — | — | 0.88 | 0.90 |

**The gap is dataset-dependent, not a constant.** `paper` loses 0.30 while `book` and `legal` lose
~0.03. `paper` is 146 chunks of Unix-philosophy prose competing against 135k chunks of a MySQL
manual; topical interference, not a funnel property. **route@1 0.70–0.93 means 7–30% of questions
put the wrong document first** — the failure `make eval` cannot see by construction. Routing runs
with rerank on and the scoped/unscoped arms above ran with it off, so the two tables are not
directly comparable. No floor yet: one measurement in one library state is a baseline, not a bar.

**Fix**: delete the stale warning; add an unscoped arm to `run_eval.py` and a `make eval-routing`
target over `run_corpus_routing.py` on datasets clearing the 20-row floor. Record `route@1`,
`route@5` and unscoped HR@5 as baselines. No threshold until the numbers exist.

Verified by: both arms on the same rows in one run, both recorded. A gap is expected; an
*unrecorded* gap is the defect.

### Retrieval by content kind

Scoped, rerank off, one library state (52 documents / 207,047 chunks), measured 2026-08-15. Every
row is a different kind of writing against the same funnel.

| golden | kind | HR@5 | MRR | nDCG@10 |
|---|---|---|---|---|
| notes | personal notes | 1.0000 | 0.9042 | 0.9281 |
| paper | essay / article | 0.8500 | 0.6783 | 0.7276 |
| d2l | technical book (md) | 0.8400 | 0.6413 | 0.7240 |
| play | script (verse dialogue) | 0.6500 | 0.4317 | 0.5082 |
| book_alice | novel | 0.6000 | 0.4067 | 0.5118 |
| study | technical book (PDF) | 0.5667 | 0.4186 | 0.4903 |
| legal | legal / political essays | 0.5500 | 0.3789 | 0.4487 |
| book | novel (Wells) | 0.5250 | 0.3792 | 0.4878 |
| odyssey | epic verse | 0.4500 | 0.3454 | 0.4122 |
| book_frankenstein | novel (epistolary) | 0.3500 | 0.2267 | 0.2891 |

**Retrieval quality is a property of the writing, and the spread is 0.35 to 1.00 on one funnel.**
Expository and structured text scores highest; narrative fiction is the hard class, and the four
novels occupy four of the bottom five rows. `book` was already documented as "the hardest dataset,
not the typical one" — the generalisation is that *fiction* is the hard kind, and Frankenstein is
half of d2l.

Two consequences for the plan. Tuning retrieval against a fiction-heavy gate optimises the worst
case for a product whose users mostly load technical documents; and a model or funnel change that
moves one kind may not move another, so a per-kind table is the honest unit of comparison rather
than a mean across datasets. Nothing is gated on these except the five already in `make eval`;
they are baselines in one state, and the fingerprint is recorded with each.

### Where the per-kind table leads: a model chosen for what someone reads

Not a stage yet, and it cannot become one before P6 — but it is what the per-kind table is for,
so it is written down where the numbers are.

Retrieval scores 0.35 to 1.00 across kinds on one funnel, and the same is expected of generation
once the matrix runs per kind rather than per dataset mean. If a candidate model is better on
technical prose and worse on narrative, that is not a tie to be averaged away: it is a choice that
depends on what a particular person loads. A reader whose library is manuals and papers and one
whose library is novels are different products wearing one binary.

What has to exist first, in this order:

1. **P6 reports per kind**, not per dataset mean. The matrix already runs the model-sensitive
   runners; grouping their output by kind is the difference between "model A scored 0.71" and
   "model A is better on tech and worse on fiction".
2. **A library profile.** The content type of what a user has actually ingested is already
   stored, so the profile is a query, not a new model: `tech_book`/`tech_article`/`paper` against
   `book`/`conversation`.
3. **P3's registry carries per-kind calibration.** `ModelProfile` already holds capability; a
   per-kind score vector is the same shape of fact, produced by the matrix rather than authored.
4. **The recommendation is a proposal, never an automatic switch.** A model change alters every
   answer a user has learned to expect; Settings proposes with the evidence — "your library is 80%
   technical; candidate B scores higher there" — and the person decides.

The falsifier is worth stating: **if the per-kind spread between candidate models is smaller than
the run-to-run variance measured in E4, there is nothing to choose between them** and this whole
direction is a dead end. Measure that gap before building any of it.

### E9 — Coverage holes that block the switch specifically

**Ingestion fidelity now measured per document kind** (`make eval-ingest ALL=1` →
`run_ingest_eval.py --all-documents`), over every complete document in the library rather than the
12 manifest ones. Measured 2026-08-15, 47 documents:

| format | docs | min retention | mean | max duplication |
|---|---|---|---|---|
| txt | 15 | 94.2% | 98.5% | 1.41 |
| md | 13 | 87.2% | 97.7% | 1.60 |
| pdf | 18 | 88.6% | 97.5% | **3.58** |
| epub | 1 | 100.0% | 100.0% | 1.09 |
| wav | 4 | — | — | — |

By content type — the chunker and prompt path the product chose, which is a
different partition from format:

| content type | docs | min retention | mean | max duplication |
|---|---|---|---|---|
| book | 17 | 94.2% | 98.8% | 3.58 |
| conversation | 4 | 97.5% | 98.9% | 1.41 |
| paper | 4 | 91.9% | 97.4% | 2.01 |
| tech_article | 14 | 87.2% | 97.5% | 2.68 |
| tech_book | 8 | 88.6% | 96.7% | 3.20 |

**A play, a legal corpus and a novel all arrive as `book`.** The product has six content types
and the goldens distinguish nine kinds, so any difference between a script and a statute is
emergent from the text, not chosen by the pipeline. That is worth knowing before attributing a
score to a "legal path" that does not exist.

Three findings the manifest-only run could not have produced:

- **EPUB first read 0.3% retention, and the defect was the reader.** `read_document_text` — the
  function the eval-integrity rule names as the one true way to read a corpus — dispatched only on
  `.pdf` and decoded everything else as bytes, so an EPUB returned
  `PK\x03\x04 … application/epub+zip`. Fixed by extracting through ingestion's own `_epub_text`;
  the same hole was open for `.docx` and is closed with it. Re-measured: **100.0%**. A golden
  generated from an EPUB before this would have asked questions about the zip container, which is
  exactly the PDF failure that produced this rule in the first place.
- **The PDF path chunks 2–3.6× denser than text.** `matrix_calculus_for_dl`: 602 chunks of median
  45 tokens over a 12,277-token source. Diagnosed rather than assumed — only 6 distinct tokens
  appear in chunks and not in the source, so this is overlap, not text the reader missed. DDIA
  carries 11,431 chunks per copy at 3.58×.
- **Audio is unmeasurable by this method and says so.** Four `wav` documents reach chunks through
  transcription, so the file on disk holds no text to compare against. Reported as a coverage gap
  rather than scored 0%.

If the switch fails, it fails on JSON-emitting generation — the paths with tolerant parsers behind
them, which are the least measured part of the suite.

| Surface | State | Needed |
|---|---|---|
| Flashcards | Runner exists, 6 golden rows, no make target | ≥30 rows, a target, P2 structural metrics |
| Summaries | Invalid (E3) | Fixed in Stage 2; target and baseline here |
| Corpus routing | Runner exists, no target | Target (E2) |
| Intent | Gated at 0.85, measured 1.0000 on 50 rows | Adversarial rows — a saturated metric cannot show a regression, and the classifier is model-sensitive |
| Concepts, tagging, vision JSON | Only topics gated, on `d2l` | Structural tier per path |
| `code` dataset | 5 rows, and **the product cannot ingest its source** | Reproduced 2026-08-15: `POST /documents/ingest` with `DATA/code/embedder.py` returns 400, "Unsupported file type '.py'" (`documents.py:134`). The reported 0/5 was not a chunking defect — the document could never have been indexed. Decide whether `.py` becomes a supported kind or the dataset is regenerated against code as it actually reaches the product, inside markdown. Do not gate it either way until then |
| Socratic, teach-back, Feynman, FSRS, multi-turn, graph | No runner | Out of scope for the switch; named so the gap is not mistaken for coverage |

### E11 — The eval cannot see a dropped citation — **already shipped**

Closed before this stage opened, and verified rather than rebuilt: `/qa` reports
`citations_proposed`, `citations_gated` and `citations_dropped` in its `done` event under
`include_context` (`qa.py:1092-1096`), and `run_eval` records all three. Confirmed on a live
answer — 2 proposed, 0 gated, 0 dropped. The plan entry was stale.

---

## Stage 4 — Extract the seams

### P3 — Model registry and role router

Model choice resolves in five places today, and two bypass the settings service entirely
(`services/flashcard.py:102`, `services/flashcard_generators.py:78`), so **a model chosen in
Settings does not apply to flashcard generation.**

- `app/model_registry.py` at the Config layer — frozen `ModelProfile` entries carrying both halves:
  *footprint* (resident bytes, licence, `min_ram_gb`) and *capability* (`supports_json_schema`,
  `thinking_default`, `usable_context`, `recommended_ctx`, `accommodations_needed`).
- `app/services/model_router.py` — one entry point, `resolve(role, *, background=False)`.
- `LLMService` gains `role=`; callers stop passing model strings. Roles: `chat`, `generation`,
  `background`, `vision`.
- `components.CATALOGUE` becomes a projection of the registry, which is what its docstring already
  promises.
- Delete the direct readers at `image_enricher.py:214`, `flashcard.py:102`,
  `flashcard_generators.py:78`, `llm.py:111`, `llm.py:312`, `routers/monitoring.py:196`.

Verified by: `make ci` with `layer_linter`'s `KNOWN_VIOLATIONS` not growing; a test that no service
module reads `LITELLM_*` from config; a smoke script proving a Settings model change reaches
flashcard generation.

Falsifier: if four roles prove too coarse, **add a role, never a per-call-site model override** —
the point is that call sites name work. If too fine, collapse to interactive/background and keep
vision as a capability flag.

### P4 — Prompt contracts and accommodations

`PromptSpec` carries the contract; `Accommodation` records each compensation with its `kind`,
`introduced_for`, `because` and `drop_when`. `render(spec, profile)` emits the contract plus only
what that model still needs — inverting today's default, where the prompt is written for the
weakest model and every model inherits the crutches. Native `response_format` replaces English
format-policing where the profile supports it (only 2 of ~28 sites use it today).

Starting inventory to tag: the hardcoded worked example and `'\n'`-escape hint in
`FLASHCARD_USER_TMPL`; the `'vs'` and `warning` routing rules in `TECH_FLASHCARD_USER_TMPL`; the
`STEP 1 / STEP 2` decomposition in `NOTES_CONCEPT_EXTRACT_SYSTEM`; the "no markdown fences"
policing throughout; the `card_field` key aliases.

Scope discipline: 28 service files carry prompts. **Convert only the JSON-emitting generation
paths** — flashcards, concepts, topics, tagging, intent, vision. Leave prose-only prompts alone
until there is evidence they cap anything. This refactor makes the real prompt exist only at
runtime, which is a genuine regression in debuggability: `make prompt-dump TASK=… MODEL=…` ships in
the same PR or the change is net-negative for anyone doing prompt work.

Verified by: golden rendered-prompt snapshots per (task, profile); the widened I-28 taxonomy guard,
which immediately catches `flashcard_prompts.py:140`; `make ci` and `make smoke`.

Bright line if tagging turns into an argument: anything that exists because of observed model
behaviour rather than a product requirement is an accommodation — and if nobody can name the
observation, it is dead code, so delete it.

#### The root cause this closes

**Luminary has no way to tell an invariant of the domain from an accommodation for a model.** Both
are prose in the same file with the same authority. I-28 says a generation prompt states the shape
of what it wants, never the name of a taxonomy, guarded by `tests/test_suggestions.py`; meanwhile
`services/flashcard_prompts.py:140` opens with "creating flashcards based on Bloom's Taxonomy" and
enumerates L1–L6 — the same defect, unguarded, because the invariant was written about one screen
rather than as a property of every prompt. Accommodations therefore never expire, and one that
never expires is a ceiling. The goal is not model-agnostic prompts, which is wishful; it is making
every compensation **typed, attributed and expiring**, so adopting a model is an audit rather than
an act of hope.

### E7 — The tuning set is the gate set

`RERANK_MODEL` and `RERANK_BLEND_ALPHA` were selected by a 12-document sweep over the goldens that
gate, on constraints naming specific datasets — best mean HR@5, "no dataset >1 question below
no-rerank" (which `time_machine` decided), and lifting `hamlet` from .567 to .667
(`backend/app/config.py:92-98`). That is documented model selection, not a hard-coded favour. The
defect is narrower and real: **there is no held-out data**, so nothing distinguishes a retrieval
improvement from a fit to twelve documents.

**Fix**: a frozen tune/holdout split declared in one place. Sweeps read tune only. The holdout is
measured and recorded on every gated run and never used to select a value. A change that improves
tune and not holdout is a fit.

Verified by: re-running the reranker sweep reproduces the current default on the tune set, and the
holdout numbers are committed as a separate baseline.

### E8 — Golden provenance is not recorded

`evals/realign_hints.py` dumps the top-5 chunks for rows whose hint is not retrieved, so a
corrected hint can be picked by hand. Replacing a non-verbatim hint with a verbatim one is correct;
picking among verbatim candidates by what the retriever surfaced makes the retriever define its own
target. Nothing records which happened.

The exposure is bounded — `test_golden_integrity.py` already requires every hint to resolve in the
source as ingestion reads it, and ratchets ambiguous-hint counts (`paper: 2`, `odyssey: 2`) down
only. What is missing is provenance.

**Fix**: per-row provenance in each `*.meta.json` (`generated`, `corrected-verbatim`, `realigned`),
and no realignment on a gated dataset without a recorded reason. A dataset carrying `realigned`
rows is reported at the top of its run.

---

## Stage 5 — Schedule and calibrate

### P5 — Scheduling and admission control

**Single residency fixes memory and makes contention worse.** I-31 states it directly: each loaded
model gets its own runner with its own slots, so text and vision do not contend. Two runners is an
isolation property; collapsing roles onto one model spends that isolation to buy back ~6GB.

From the benchmark in `1195f4f` and the table in I-31 — M3 Pro, 450-token generations — at 1 slot
with 4 callers, aggregate throughput stays ~55 tok/s and per-call latency staircases: 4.5 / 8.9 /
13.5 / 17.8s. Background calls are large (a whole section; a recorded 4.3k-token prompt) with ~0.4s
of prefill against ~16s of decode, so an Ask arriving during the deferred window waits roughly one
background call — 10 to 20 seconds — before its *first token*. On the low profile that is the
default, not the worst case. **Residency is a memory control with no latency term in it: left
alone, the plan trades a crash for a stall.**

- `background=` already annotates call sites across the services (`document_tagger`, `note_tagger`,
  `prereq_extractor`, `gap_detector`, `concept_linker`, `flashcard_audit`, and more) but carries
  only routing meaning. Give it scheduling meaning — a change inside `LLMService`, not at thirty
  callers.
- `app/services/llm_admission.py` — a priority gate in front of the runtime's slots. Interactive
  acquires immediately; background checks interactive pressure before issuing its *next* call. A
  grace window (~5s) after an interactive call so a multi-turn chat is not interleaved.
- Background call-size caps are largely already built (`49c8806` shrinks the per-unit cap as a
  document grows; `1195f4f` added `WEB_REFS_MAX_SECTIONS`). What is missing is the framing: yield
  granularity is one completed call, so **worst-case interactive wait equals the longest background
  call**. Those caps are a latency bound, not only the cost control I-31 describes. Audit the
  remaining background call sites for an unbounded prompt rather than adding new caps.
- Profile-conditioned policy: `low` hard-suspends, `standard` reserves a slot, `performance`
  separates physically.
- An explicit "Indexing paused while you're asking" state in the UI — I-10 requires an explicit
  state anyway, and a stated pause reads as control where a silent one reads as broken.

Verified by: P0's latency probe on all three profiles — interactive TTFT under ingest load within
*N*× of idle, with *N* taken from the baseline rather than invented — plus a test that a background
call yields under interactive pressure. **Measure ingestion throughput too**, or you trade a stall
for an ingest that never finishes.

Falsifier: if hard-suspend on `low` makes ingest unacceptable for people who upload and walk away,
suspend only while a chat is actively streaming and resume on idle. If yielding between calls is
still too coarse, the lever is call size, not preemption — Ollama exposes no preemption primitive.

### P6 — Eval matrix and calibration

`evals/run_model_matrix.py` drives the model-sensitive runners (`run_intent_eval`,
`run_flashcard_eval`, `run_summary_eval`, `/qa`) across candidates, with two arms the previous
attempt lacked:

- a **scaffolding-tax arm** — shipped prompt versus bare contract. If a model scores higher on the
  bare contract, the accommodation set is its ceiling.
- an **accommodation necessity check**, whose output is `accommodations_needed` on the registry
  entry.

Metric tiers apply from here onward:

| Tier | Metrics | Role |
|---|---|---|
| Structural | Raw parse rate before repair, repair-kind counts, schema conformance, requested-count adherence, first-pass acceptance, citation validity, non-empty answer rate | Gates a model swap |
| Quality | Faithfulness/HHEM, judged answer quality | Report only — cross-model deltas are style artifacts |
| Excluded | hit_rate, MRR, nDCG | No generation-model term; including them lets retrieval noise be blamed on a model |

Verified by: re-running on llama3.2 reproduces committed numbers, then the phase's own acceptance
test — **the matrix must visibly separate `qwen3.5:0.8b` from `qwen3.5:4b`.** Two models that
different must not score alike.

Falsifier: if it cannot separate them, the instrument is still blind. Go back to P2 and add metrics
until it can. **Do not choose a model on a blind instrument.** That is exactly what happened last
time.

---

## Stage 6 — Switch and lean out

### P7 — Memory profile and the model switch

`LUMINARY_MEMORY_PROFILE: low | standard | performance`, defaulted from host RAM. Reuse
`total_memory_gb()` and `_mem_gb()` rather than adding a third detector. The profile picks the role
map **and** the slot policy from P5 — footprint and latency isolation move together. `vision_model`
retires as a first-class knob and becomes the `vision` role's resolution. The I-31 amendment lands
here, in the PR that makes it true.

Verified by: all three gates together, on all three profiles — P0 footprint, P5 latency, P6
structural — plus the residency test `len({resolve(r).model for r in ROLES}) <= max_resident[profile]`.

Falsifier: if `qwen3.5:4b` fails a structural gate, **swap the id in the registry and re-run — do
not patch prompts.** But if *every* candidate fails a gate that llama3.2 passes, that gate is
encoding a llama3.2 accommodation and belongs in P4's audit, not in the gate set.

### P8 — Lean-out and surfacing

- Delete accommodations the calibration proved unnecessary. This is the payoff of P4's attribution:
  deletion becomes evidence-driven rather than nervous.
- Delete tolerant-parser paths if P2 showed near-zero repairs on the shipped model.
- Bloom labels: render the verb, not a bare `L3`, at `DeckHealthPanel.tsx:55` and `:159`.
- Surface resident models, their measured size, and the active profile in Settings.
- **Do not touch the embedder.** bge-small is 0.13GB and I-9 pins 384 dimensions; replacing it is a
  full corpus re-embed behind a migration to save ~100MB.

Verified by: `make ci`, `make smoke`, surface-manifest coverage, and a footprint delta from P0.

Falsifier: feature deletion is irreversible in practice. Each removal needs explicit sign-off, and
no deletion ships inside a refactor PR — if the refactor is reverted, the deletion must not come
back with it.

### E10 — No labelled data, so no quality bar anywhere

Every generation floor is a collapse detector derived as `mean - 3sd`. `faithfulness` sits at 0.30
because the observed distribution is unimodal, with no gap between grounded and hallucinated
answers to place a bar in. The citation judge scores its own notion of support and nothing
establishes that notion is right.

**Fix**: 60–100 answers labelled grounded / not-grounded, and the same answers' citations labelled
supported / not. That one set validates the judge, makes a real faithfulness bar derivable, and
anchors the structural tier.

Last because it is the only item needing human labelling time, and everything above it is decidable
without one. It can start in parallel at any point. **Do not raise the faithfulness floor without
it** — 0.65 would have failed 11 of 12 healthy answers.

---

## Reference — footprint

Estimates from published quantised weight sizes plus measured figures in this repo. P0 replaces
them with measurements.

| Component | Source | Resident |
|---|---|---|
| Ollama chat runner, llama3.2 Q4 + KV@8192 | `components.py` `chat_model` | ~2.5GB |
| Ollama vision runner, qwen2.5vl:7b Q4 + ViT + KV | `config.py:124` | ~6.5GB |
| GLiNER `gliner_multi_pii-v1` | `model_prefetch.py` spec, 1126MB | ~1.2GB |
| Cross-encoder L-12 + bge-small | `config.py:98`, `embedder.py` | ~0.3GB |
| Python + torch + PyMuPDF baseline | | ~1.3GB |
| Tauri WebKit | | ~0.5GB |
| macOS baseline | | ~3.0GB |

Both Ollama runners are resident simultaneously because `spawn_ollama` sets
`OLLAMA_KEEP_ALIVE=30m` but never `OLLAMA_MAX_LOADED_MODELS`, whose Ollama default is 3.
`scripts/install.sh:198` and `scripts/bootstrap.sh:257` both cap it; the DMG path does not.

Summed against a 16GB host: **~15.3GB during a PDF ingest today, projected ~8.1GB after P1 and
P7** — one runner instead of two, and the vision runner released rather than held for 30 minutes.
Both figures are estimates until P0 measures them; they are good enough to choose a direction and
not good enough to commit to a threshold.

## Reference — profiles

A memory profile is a constraint on the role→model map **and** a latency-isolation policy. Two
roles resolving to different model ids cost two resident runners whatever
`OLLAMA_MAX_LOADED_MODELS` says.

| Profile | RAM | chat / generation / background / vision | Slots | Contention |
|---|---|---|---|---|
| low | <12GB | all `qwen3.5:2b` | 1 | Background suspends while a session is active |
| standard | 12–24GB | all `qwen3.5:4b` | 2 | One slot reserved for interactive |
| performance | ≥24GB | `9b` / `9b` / `0.8b` / `4b` | 2–4 | Background on its own runner |

A slot costs a full `OLLAMA_NUM_CTX` of KV cache — 896MiB for a 3B (I-31), so ~1.2GB for a 4B at
8192. The reserved lane in `standard` is only affordable once the 6.5GB vision runner is gone,
which is why P7 pays for P5.

Qwen 3.5 is the only family that makes this table buildable: every variant 0.8b–9b is natively
multimodal at 256K context, so one family covers all four roles at three sizes. Kimi has no
self-hostable variant. DeepSeek's small variants are reasoning distills, which conflict with the
global `think=False` (`llm.py:227`) that exists because thinking traces burn `num_ctx` before any
answer token. Gemma 4 / Gemma 3 4B is the fallback candidate, gated on JSON validity rate — its
documented weakness is strict instruction adherence, and Luminary's non-chat surface is almost
entirely JSON-shaped.

## Reference — what the suite can decide today

| Change under test | Decidable | Binding limit |
|---|---|---|
| Embedder, reranker, fusion weights (scoped) | with care | Tuning set is the gate set (E7); hint matching is coupled to chunking (E6) |
| Chunking or parse change | no | HR@5 moves on chunk boundaries for non-retrieval reasons (E6) |
| Cross-document routing | no | Every gated arm pins `document_id` (E2) |
| Answering-model swap | no | No structural metric (P2); one run cannot resolve the delta (E4) |
| Generation prompt change | partial | Floors on `book` + `paper` only; ±0.10 on book is noise |
| Summaries | no | The metric is invalid as written (E3) |
| Flashcards, topics, tagging under a new model | no | Flashcard runner has no target; intent saturated at 1.0 (E9) |
| Interactive modes, FSRS, concept graph, enrichment | no | No runner exists |

## Reference — measured baselines

One library state, bit-reproducible on re-run. **Compare a change against these, never against a
floor.** Every number here predates E5, so its library state is recorded in prose rather than in
the run.

### Retrieval

| dataset | source | rows | flagged | chunks | HR@5 / MRR / nDCG@10 |
|---|---|---|---|---|---|
| book | time_machine.txt | 40 | 2 | ~1.6k | 0.5750 / 0.3979 / 0.5074 |
| paper | art_of_unix.txt | 40 | 3 | 146 | 0.8500 / 0.7025 / 0.7461 |
| legal | federalist_papers.txt | 60 | 0 | 2537 | 0.5333 / 0.3728 / 0.4508 |
| play | hamlet.txt | 60 | 5 | 394 | 0.6500 / 0.4406 / 0.5263 |
| study (PDF) | sutton_barto_rl.pdf | 60 | 17 | 1939 | 0.5833 / 0.4136 / 0.4832 |
| thoughts | daily_thoughts_2026.txt | 4 | 0 | 7 | 1.0000 / 1.0000 / 1.0000 |

`study` is the only measurement of the **PDF parse path**; before 2026-08-12 `generate_golden.py`
read sources as bytes, so a PDF produced questions about `%PDF-1.5 /FlateDecode`. `thoughts` reads
1.000 because top-5 over a 7-chunk document returns most of it — a property of a 2,944-char source,
not of retrieval, which is why it is measured and never gated. `make eval` covers the other five.

`paper` was not fit to gate on and was regenerated 2026-08-12: `art_of_unix.txt` is a scrape
carrying site chrome interleaved with prose (460 of 2166 lines, 118 of 248 chunks). Fixed in
ingestion, not in the corpus — `app/services/source_text.py` collapses repeating furniture and
`generate_golden.py` reads through it, so generator and ingestion see one document.

| | before | after |
|---|---|---|
| chrome-sourced questions | 17 / 40 | **0** |
| ambiguous hints | 18 / 40 | **2** |
| distinct hints | 32 | 39 |
| index | 248 chunks | 146 chunks |
| MRR across re-runs | drifted 0.0125 | bit-identical |

Before and after are not comparable — different questions against a different index. What is
established is that the dataset now measures the book, reproducibly. Hint integrity is verified:
40/40 hints and 40/40 graded passages resolve in the corpus for both `book` and `paper`.

### Generation — the standing baseline

Marker citations: `pack_context_indexed` labels each emitted passage `[S<n>]`, the model cites
`{"source":"S1"}`, and the backend fills the excerpt from that chunk — verbatim by construction,
carrying the `chunk_id` that makes the chip deep-linkable. Measured 2026-08-13, judge
`ollama/qwen2.5:14b-instruct`, retrieval bit-identical to the table above.

| | book | paper |
|---|---|---|
| faithfulness (HHEM) | 0.6855 | 0.7012 |
| answer_relevance | 0.6729 | 0.8527 |
| citation_support_rate | 0.6754 | 0.7449 |
| citation_coverage | 0.8571 | 0.9744 |
| answer_rate | 0.8750 | 0.9750 |
| citations proposed / gated / dropped | 63 / 6 / 0 | 49 / 0 / 0 |

`make eval-gen` has not been re-run as a distribution against this design, so **the floors stay
untouched**: one measurement per dataset is not a distribution, and a bar set now would be
calibrated against a design that has already changed. E4 is what makes the re-run meaningful.

All six kinds, one run each on the marker build (`book`/`paper` are the 4-run means):

| dataset | HR@5 | support | coverage | answer_rate | faithfulness | answer_relevance |
|---|---|---|---|---|---|---|
| book | 0.5750 | 0.6491 | 0.8245 | 0.9250 | 0.6888 | 0.6729 |
| paper | 0.8500 | 0.7089 | 0.9679 | 0.9750 | 0.6802 | 0.8527 |
| legal | 0.5333 | 0.7476 | 0.9500 | 1.0000 | 0.7375 | 0.7376 |
| play | 0.6500 | 0.7338 | 0.9286 | 0.9333 | 0.5660 | 0.7321 |
| study (PDF) | 0.5833 | 0.7167 | 0.9000 | 1.0000 | 0.6145 | 0.7852 |
| thoughts | 1.0000 | 1.0000 | 0.7500 | 1.0000 | 0.6309 | 0.8759 |

Every kind clears every derived floor and `citations_dropped` is 0 everywhere: no ungrounded
excerpt reached a user on any corpus. **`book` is the weakest dataset, not the representative one**
— the other five score 0.72–1.00 on citation support against book's 0.65, so the citation work was
tuned against the hardest case. `play` carries the lowest faithfulness (0.5660) because Hamlet is
verse and dialogue while HHEM scores prose entailment, the same style artifact that bars
cross-model faithfulness comparison. `study` recorded `judge_failed_calls: 1` of ~90; a number
quoted from that row should say so.

### Variance, and the floors derived from it

Four runs per dataset on one frozen build, same corpus, bit-identical retrieval:

| | citation_support_rate | citation_coverage | answer_rate | faithfulness |
|---|---|---|---|---|
| book | 0.6491 ± 0.0521 | 0.8245 ± 0.0628 | 0.9250 ± 0.0354 | 0.6888 ± 0.0120 |
| paper | 0.7089 ± 0.0254 | 0.9679 ± 0.0323 | 0.9750 ± 0.0000 | 0.6802 ± 0.0168 |

**A single run cannot resolve a change smaller than ~0.10 on book or ~0.05 on paper.** book's
support rate ranged 0.5893–0.7065 across identical runs and `citations_proposed` ranged 49–71: the
model's citation volume is itself unstable, which is most of the spread. Two structural changes
were credited with moving this metric by less than that band; both were inside the noise and
neither claim survives. Retrieval metrics are exempt — bit-reproducible on a fixed corpus.

Floors are `mean - 3sd` for the weaker dataset, rounded down to 0.05: `citation_support_rate` 0.45,
`citation_coverage` 0.60, `answer_rate` 0.75. They replace 0.80s that were invented with no
derivation. Support at 0.65 is not good; it is what this build scores.

### What these numbers cost to learn

Three findings that will otherwise be re-derived:

- **`citation_support_rate` had never once computed.** Two independent reasons each hid the other:
  it paired claims by splitting prose on `[N]` markers the product never emits, and `judge_citation`
  imports `litellm`, absent from the `evals` project, so every call raised `ModuleNotFoundError`
  into a swallowed counter. I-32 is what surfaced both.
- **The 0.485 first measurement was two stacked defects.** The product fabricated quotes (closed by
  I-33: excerpts are verified against the grounding and dropped when absent), and the judge prompt
  demanded each excerpt "fully support the claim", which no single excerpt can do — it scored `no`
  on a verbatim correct citation while giving a fabricated commentary chip a `yes`. Scores recorded
  before that change are not comparable to scores after it.
- **The metric was measuring the excerpt window, not the citation.** 12 of 15 `book` chips were
  head cuts of their chunk; judged on the full chunk the same chips scored 0.8667 against 0.5667,
  8 of 15 verdicts flipping and none the other way. Selecting the window against the answer moved
  support 0.5000 → 0.6754 (book) and 0.4500 → 0.7449 (paper) with retrieval, prompt and proposals
  unchanged. The lesson is the metric's own: **judge what the product shows, and confirm the metric
  scores the object you think it does before optimising against it.**

## Reference — corrections to the audit reports

Acting on these as written would waste work or make the harness worse.

| Claim | Status |
|---|---|
| Unscoped eval is unreliable because `/search` group-flattening breaks rank order | **Stale.** `run_eval.py:319` sorts by `global_rank`. The warning at `:274` is wrong and goes with E2 |
| Small datasets (`code` 5, `thoughts` 4, `conversation` 18) produce false CI signals | **Already prevented.** `_TOO_SMALL_TO_GATE` records and never gates them; `make eval` runs five datasets, none small. The real defect is that those surfaces are unmeasured (E9) |
| Metrics can be defaulted or fabricated to fill a gap | **Already closed.** I-32; `run_eval.py:1009-1060` fails a requested-but-uncomputed metric and skips only what was never requested |
| Raise the faithfulness floor to ~0.55 | **Reject.** No labelled data to derive a bar from, a unimodal distribution, and cross-model HHEM deltas are style artifacts. Build E10 first |
| Reranker choice is benchmark favouritism | **Overstated.** Documented selection on a sweep. The defect is the missing holdout (E7) |
| `paper` is corrupt and scores above `book` | **Fixed 2026-08-12**, see the regeneration table. Pre- and post-fix numbers are not comparable |
| Per-dataset pass rates from `audit_golden.py --all` (`book_frankenstein` 47.5%, `code` 0/5) | **Not reproduced.** They need a live backend in a known library state. Reproduce with an E5 fingerprint attached before treating any as a finding |

## Reference — duplication removed by these stages

Measured on `ba0c1db`.

| Finding | Evidence | Stage |
|---|---|---|
| `_splitter_cls` triplicated verbatim | `tech_book_chunker.py`, `paper_chunker.py`, `ingestion_nodes/chunk.py` — identical docstring and body | standalone chore |
| Two tolerant-JSON implementations | `llm_json.py` (149 lines) plus a second ladder in `flashcard_parsers.py` (254 lines) | 3 (P2) |
| Five model-resolution paths | Two bypass `settings_service` | 4 (P3) |
| 28 cross-module private-name imports | Worst: `settings_service._cache` from `main.py:67` and `routers/settings.py:293` | 4 (P3) |
| RAM detection written three times | `install.sh:_mem_gb`, `bootstrap.sh:MEM_GB`, `supervisor.rs:total_memory_gb()` | 6 (P7) |
| ~~Entity model id hardcoded in three places~~ | `ner.py` ×2 plus `model_prefetch.py`; now `NER_MODEL` | done, P1 |

Checked and cleared: `_fire_and_forget` in four modules is a one-line alias over a shared helper.
The graph cluster (2524 lines, 7 files) is a decomposition by concern.

Unassigned: the flashcard cluster is 3233 lines over 9 files and the generators extraction is
half-done — `FlashcardService` thin-delegates per its docstring but still imports `_CLOZE_BLANK_RE`
from `flashcard_parsers`. That needs a decision about what `FlashcardService` is for, not a task.

**Do not add a cleanup phase. Add a ratchet.** The repo already trusts this mechanism:
`layer_linter.py`'s `KNOWN_VIOLATIONS` may only shrink. Apply the same shape to quality — a
private-cross-import check with a frozen allowlist and a duplicate-block count, both wired into
`make ci`. The per-stage rule is then simple: a PR leaves its touched area with no new duplicate
and no new private cross-import, and removes the duplication lying in its own path.

## Reference — invariants

Reworded on this branch; all five describe things that already exist.

| | Change |
|---|---|
| I-9 | Dimension is a stored property of the corpus. The embedder is not pluggable the way a generation model is; replacing it is a re-embed behind a migration |
| I-16 | "Prioritize Ollama" → a fresh install works with no account, key or network |
| I-27 | One context window per loaded model, resolved from the model. A 256K capability is not a budget |
| I-28 | Rationale is portability, not "a small local model does not infer a pedagogy". Names the guard's gap: `flashcard_prompts.py` still enumerates Bloom levels |
| I-31 | Heading generalised to "the runtime's serving width". The text/vision isolation sentence is deliberately untouched — amending it now would document a role collapse that does not exist yet |

Warranted but not yet written, because each needs its guard first. Adding them early would break
the standard that makes the file worth reading.

| Rule | Stage | Guard |
|---|---|---|
| Model choice resolves through the registry; no service reads a model name from config | 4 (P3) | Config-read test |
| A compensation for model behaviour is a typed, attributed, expiring accommodation — never an invariant, never an inline prompt string | 4 (P4) | Render-path guard |
| Background LLM work yields to interactive work; `background=` is a scheduling priority | 5 (P5) | Yield test + latency gate |
| A memory profile constrains the role→model map; roles resolving to distinct ids cost distinct runners | 6 (P7) | Residency test |
| An eval run records the environment that produced it; runs with differing fingerprints are not compared | 2 (E5) | Provenance test |
| I-31 amendment: collapsing roles spends text/vision isolation | 6 (P7) | Lands with the collapse |

## Branches

| Branch | Carries | Notes |
|---|---|---|
| `fix/ollama-model-residency` | P0, P1 | Ships first and alone. The reported crash is not blocked by anything below |
| `feat/eval-run-provenance` | E5, E4 | Behaviour-neutral. Nothing else is comparable until it lands |
| `fix/eval-summary-and-hints` | E3, E6 | Two invalid-measurement fixes; no product change |
| `feat/llm-output-instrumentation` | P2 | Behaviour-neutral. Everything downstream argues from its numbers |
| `feat/eval-unscoped-and-coverage` | E2, E9, E11 | New make targets; expands goldens |
| `refactor/model-registry` | P3 | Both halves of `ModelProfile`; five direct config readers deleted |
| `refactor/prompt-contracts` | P4 | JSON paths only. Ships with `make prompt-dump` and the widened taxonomy guard |
| `feat/eval-holdout-split` | E7, E8 | Freezes tune/holdout; records golden provenance |
| `feat/llm-admission-control` | P5 | Delivers value on today's two-runner setup too, and must precede P7 |
| `feat/model-eval-matrix` | P6 | Must land before a model is chosen. This is the step that was missing last time |
| `refactor/memory-profile` | P7 | The actual switch, made against evidence |
| `chore/lean-out` | P8 | Split per deletion. Sign-off required; never bundled with a refactor |
| `feat/grounding-labels` | E10 | Human labelling; can run in parallel from any point |

## Done when

**Measurement**

- A retrieval run and a generation run each carry an environment block, and two runs from different
  library states are visibly non-comparable without reading a commit log.
- `make eval` reports scoped and unscoped arms, both baselined.
- A generation comparison is reported as a distribution against recorded sd, never as two points.
- Every gated dataset clears 20 rows and carries hint provenance.
- `make eval-summary`, `make eval-routing` and a flashcard target exist and are in the gate.
- The holdout set has never been used to select a value.
- The structural tier separates two models of different size, on the same corpus, in one run.

**Product**

- Good performance on any machine: three profiles sized from host RAM, each with a residency *and*
  a latency policy, each gated by a measured threshold on real hardware.
- Leaner code: one tolerant parser instead of two; five model-resolution paths become one;
  `_splitter_cls` once instead of three times; the vision-model knob retired; accommodations deleted
  once calibration proves them unnecessary. Both `make ci` ratchets strictly lower than at
  `ba0c1db` — 28 private cross-imports and the duplicate-block count are the committed starting
  numbers.
- Pluggable models: adding a model is write a registry entry, run the matrix, commit the calibrated
  profile. **Check by onboarding a second family (Gemma) end to end without touching a prompt
  file.** If that requires a prompt change, the refactor is not finished.
- Better experience: the crash is gone; an Ask during an upload answers promptly or says plainly why
  it is waiting; Settings shows what is resident and how large; card levels read as verbs.

The last check is the one that matters: **the 0.5.0 reporter's exact workflow — open the app, upload
a PDF, ask a question mid-ingest — on a 16GB Air.** Everything above is instrumentation for it.
