---
description: Implementation plan for model footprint, interactive/background scheduling, and model substitutability. Delete when the last phase ships.
---

# Model footprint and substitutability

Three problems reached us as one user report on 0.5.0 ("uses a lot of memory, my Mac Air
crashed loading a PDF, ~16GB"). They have different causes and different fixes.

| | Problem | Cause | Phases |
|---|---|---|---|
| Memory | ~15.3GB peak on a 16GB host | Bundle never caps resident model count | 0, 1, 7 |
| Latency | Ask queues behind ingestion | Background LLM work has no scheduling priority | 5 |
| Adaptability | Better models do not move eval numbers | Prompts, parsers and budgets tuned to llama3.2; no metric sees the difference | 2, 3, 4, 6 |

Baselined against `ba0c1db` (0.6.1), not the reported 0.5.0 build.

## What 0.6.1 already fixed

Do not re-solve these.

- `1195f4f` — `DocumentParser.parse` moved into `asyncio.to_thread`. Event-loop freeze on a
  23MB PDF: 44.9s → 3.96s. In public mode the backend also serves the SPA, so that freeze
  stopped lazy route chunks arriving and the UI could not navigate.
- `1195f4f` — `OLLAMA_NUM_PARALLEL` sized from physical RAM by every install path including
  `supervisor.rs`, which passes the same value to Ollama and the backend so they cannot
  disagree. **Copy this mechanism for `OLLAMA_MAX_LOADED_MODELS`; it was the one variable
  left out of it.**
- `49c8806` — section summaries deferred behind `stage='complete'`. Large book to readable:
  17min → 86s. Per-unit cap now shrinks as a document grows.

0.6.1 moved the heavy work off the critical path. It did not make it cheaper: deferred
summaries and enrichment still issue LLM calls into the slots an Ask needs.

## Footprint

Estimates from published quantised weight sizes plus measured figures in this repo. Phase 0
replaces them with measurements.

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

## Profiles

A memory profile is a constraint on the role→model map, and a latency-isolation policy. Two
roles resolving to different model ids cost two resident runners whatever
`OLLAMA_MAX_LOADED_MODELS` says.

| Profile | RAM | chat / generation / background / vision | Slots | Contention |
|---|---|---|---|---|
| low | <12GB | all `qwen3.5:2b` | 1 | Background suspends while a session is active |
| standard | 12–24GB | all `qwen3.5:4b` | 2 | One slot reserved for interactive |
| performance | ≥24GB | `9b` / `9b` / `0.8b` / `4b` | 2–4 | Background on its own runner |

A slot costs a full `OLLAMA_NUM_CTX` of KV cache — 896MiB for a 3B (I-31), so ~1.2GB for a
4B at 8192. The reserved lane in `standard` is only affordable once the 6.5GB vision runner
is gone, which is why Phase 7 pays for Phase 5.

Qwen 3.5 is the only family that makes this table buildable: every variant 0.8b–9b is
natively multimodal at 256K context, so one family covers all four roles at three sizes.
Kimi has no self-hostable variant. DeepSeek's small variants are reasoning distills, which
conflict with the global `think=False` (`llm.py:227`) that exists because thinking traces
burn `num_ctx` before any answer token.

## Phases

Order is: instrument, extract, schedule, calibrate, then swap.

| # | Phase | Branch | Gate |
|---|---|---|---|
| 0 | Measurement harness | `fix/ollama-model-residency` | Reproduces the ~16GB peak |
| 1 | Residency and lifecycle | `fix/ollama-model-residency` | Footprint delta, `make ci`, `make smoke` |
| 2 | Output instrumentation | `feat/llm-output-instrumentation` | Repair counters non-zero on llama3.2 |
| 3 | Model registry and role router | `refactor/model-registry` | No service reads `LITELLM_*` from config |
| 4 | Prompt contracts and accommodations | `refactor/prompt-contracts` | Rendered-prompt snapshots; widened I-28 guard |
| 5 | Scheduling and admission control | `feat/llm-admission-control` | TTFT under ingest load, per profile |
| 6 | Eval matrix and calibration | `feat/model-eval-matrix` | Separates `qwen3.5:0.8b` from `4b` |
| 7 | Memory profile and model switch | `refactor/memory-profile` | All three gates, all three profiles |
| 8 | Lean-out and surfacing | `chore/lean-out` | Both ratchets below `ba0c1db` |

### Phase 0 — measurement harness

`scripts/mem_profile.py`. Samples backend RSS, each Ollama runner via `/api/ps`, and system
memory per ingestion stage rather than at steady state, plus a latency probe issuing an Ask
during ingest and recording time to first token. Baseline commits as JSONL.

Falsifier: if peak is not dominated by the two Ollama runners, the diagnosis is wrong and
Phase 1 must be re-derived. Check `_VECTOR_RENDER_DPI=150` with `_MAX_DIM=4000`
(`image_extractor.py`) — a 4000×4000 RGB pixmap is ~48MB and up to 4 are taken per page —
and the enrichment worker for a leak.

### Phase 1 — residency and lifecycle

1. `supervisor.rs`: set `OLLAMA_MAX_LOADED_MODELS` alongside `OLLAMA_NUM_PARALLEL`, sized
   from `total_memory_gb()` — 1 under 24GB, 2 above. **Done.**
2. Vision calls pass `VISION_KEEP_ALIVE` (60s) so the runner releases when enrichment
   drains instead of holding ~6.5GB for the global 30m. **Done.**
3. `NER_MODEL` becomes a setting, replacing the model id hardcoded in three places.
   **Done** — `scripts/ner_compare.py` compares two entity models on the live corpus.

### The entity model cannot be unloaded

`retriever_strategies.py` skips `graph_expand` whenever `EntityExtractor._model is None`,
returning the query unexpanded:

```
if extractor._model is None:
    logger.info("graph_expand: GLiNER model not loaded yet; skipping expansion")
    return query
```

The guard is deliberate — it refuses to pay a 1.1GB load inside a search — but it means
deferring the model at boot, or reaping it after idle, **silently changes retrieval** rather
than only freeing memory. Both were the original items 3 and 4; both are withdrawn.

The lever is a smaller model that stays resident, not a large one that does not. The current
default is `gliner_multi-v2.1` fine-tuned onto a synthetic PII dataset across six languages,
while `ENTITY_TYPES` asks for PERSON, ORGANIZATION, PLACE, CONCEPT, EVENT, TECHNOLOGY, DATE,
LIBRARY, DESIGN_PATTERN, ALGORITHM, DATA_STRUCTURE, PROTOCOL, API_ENDPOINT — none of them
PII, and the corpus is English. `gliner_small-v2.1` is 336MB against 1126MB.

Decide it in two steps, in this order:

1. `make ner-compare` — agreement, yield, type distribution, resident cost. Reports
   disagreements to read, not a score: neither model is ground truth.
2. `make eval` under each `NER_MODEL`, comparing hit_rate/MRR. **This is the gate.**
   Entities exist to serve retrieval, so retrieval is what must not regress.

If the small model holds retrieval, it becomes the default everywhere rather than only on
small machines — the size win is then incidental to using a model that matches the label
vocabulary. If it does not, the entity model stays large and resident, and its memory comes
out of Phase 7's role collapse instead.

### Phases 2–8

Detail lives in the plan artifact until each phase opens its branch. Summary of intent:

- **2** — `parse_llm_json_*` returns `repairs: frozenset[str]`; the duplicate parser ladder
  in `flashcard_parsers.py` collapses into `llm_json.py`; first-pass acceptance and retry
  counts recorded. Behaviour-neutral. This is the model-quality signal that does not exist
  today, and everything downstream argues from it.
- **3** — `app/model_registry.py` (Config layer) with footprint and capability halves;
  `app/services/model_router.py` with `resolve(role, *, background)`. Roles: `chat`,
  `generation`, `background`, `vision`. Deletes the five direct config readers, including
  the two that bypass the settings service so a Settings-chosen model never reaches
  flashcard generation (`flashcard.py:102`, `flashcard_generators.py:78`).
- **4** — `PromptSpec` carries the contract; `Accommodation` records each compensation with
  `introduced_for`, `because`, `drop_when`. `render(spec, profile)` attaches only what a
  model needs. JSON-emitting paths only. `make prompt-dump` ships in the same PR.
- **5** — `background=` gains scheduling meaning. It already annotates call sites across the
  services, so this is a change inside `LLMService`, not at thirty callers.
- **6** — `evals/run_model_matrix.py` with a scaffolding-tax arm (shipped prompt vs bare
  contract) and an accommodation necessity check whose output is `accommodations_needed`.
  Structural metrics gate; faithfulness reports only; retrieval metrics excluded because
  they contain no generation-model term.
- **7** — `LUMINARY_MEMORY_PROFILE`. The I-31 amendment lands here, in the PR that makes it
  true.
- **8** — deletions that calibration justified.

## The eval substrate

Verified 2026-08-12, before using these numbers to choose an entity model.

`compute_hit_rate_5`, `compute_mrr` (MRR@5) and `compute_ndcg_10` in
`evals/lib/retrieval_metrics.py` are correct. The mechanism worth checking is hint matching —
a hint is normalised, truncated to `HINT_NORM_LEN=80` and substring-matched, so a hint that
is not verbatim in the corpus makes its question permanently unhittable and turns the metric
floor into a golden artifact. It is not happening: **40/40 hints and 40/40 graded passages
resolve in the corpus for both `book` and `paper`.**

`book` is sound — 40 rows, 40 distinct hints, all graded, one source, corpus clean.

**`paper` is not fit to gate on.** `art_of_unix.txt` is 2166 lines and stops being the book at
line 1734, continuing as scraped ibiblio site chrome: a "Page not found" page, nav menus, and
a footer. 118 of 248 chunks (48%) carry it, and **13 of 40 golden questions (33%) ask about
it** — "page not found?", "what is ibiblio, exactly?", "terasaur?". Only 33 distinct hints
cover the 40 questions, the most reused being the 404 message itself.

Those questions inflate rather than depress `hit_rate`: `terasaur` and `ibiblio` are unique
tokens, so BM25 finds them immediately. `paper` also carries the lowest thresholds of any
dataset (0.45/0.30 against the 0.50/0.35 default), which suggests the bar was lowered instead
of the data fixed. Every other corpus is clean — the odyssey 1/1588, d2l 1/952, the rest zero.

Consequence for the entity-model decision: **read it off `book` only**, where the two models
are bit-identical. The `paper` mrr difference of +0.012 is measured on the contaminated third
and is discarded.

Repair order. Six test files reference the fixture (`test_cross_domain_goldens`,
`test_performance`, `test_book_parser`, `test_integration`, `test_integration_full`,
`test_e2e_upload`), so truncation shifts chunk counts; nothing in `evals/` or `scripts/`
references it by name.

1. Truncate at the seam (~line 1733), checking nothing real is lost.
2. Run the six dependent tests; fix assertions encoding the old size.
3. Re-ingest, regenerate `paper.jsonl` with `generate_golden.py`, cross-verify with
   `audit_golden.py`.
4. Re-baseline the paper thresholds. Expect `hit_rate` to fall — the easy chrome questions
   disappear, so a lower number is a real bar replacing a flattered one.
5. Re-run the entity-model comparison against two clean datasets.

## Metric tiers

Applies from Phase 6 onward.

| Tier | Metrics | Role |
|---|---|---|
| Structural | Raw parse rate before repair, repair-kind counts, schema conformance, requested-count adherence, first-pass acceptance, citation validity, non-empty answer rate | Gates a model swap |
| Quality | Faithfulness/HHEM, judged answer quality | Report only — cross-model deltas are style artifacts |
| Excluded | hit_rate, MRR, nDCG | No generation-model term; including them lets retrieval noise be blamed on a model |

## Duplication removed by these phases

Measured on `ba0c1db`.

| Finding | Evidence | Phase |
|---|---|---|
| `_splitter_cls` triplicated verbatim | `tech_book_chunker.py`, `paper_chunker.py`, `ingestion_nodes/chunk.py` — identical docstring and body | standalone chore |
| Two tolerant-JSON implementations | `llm_json.py` plus a second ladder in `flashcard_parsers.py` | 2 |
| Five model-resolution paths | Two bypass `settings_service` | 3 |
| 28 cross-module private-name imports | Worst: `settings_service._cache` from `main.py:67` and `routers/settings.py:293` | 3 |
| RAM detection written three times | `install.sh:_mem_gb`, `bootstrap.sh:MEM_GB`, `supervisor.rs:total_memory_gb()` | 7 |
| ~~Entity model id hardcoded in three places~~ | `ner.py` ×2 plus `model_prefetch.py`; now `NER_MODEL` | done, 1 |

Not violations, checked: `_fire_and_forget` in four modules is a one-line alias over a
shared helper. The graph cluster (2524 lines, 7 files) is a decomposition by concern.

Unassigned: the flashcard cluster is 3233 lines over 9 files, and the generators extraction
is half-done — `FlashcardService` thin-delegates per its docstring but still imports
`_CLOZE_BLANK_RE` from `flashcard_parsers`. Needs a decision about what `FlashcardService`
is for, not a task.

Enforcement is a ratchet in `make ci`, in the shape `layer_linter.py` already uses: a
private-cross-import check with a frozen allowlist, and a duplicate-block count. Both may
shrink, never grow.

## Invariants

Reworded on this branch — all five describe things that already exist:

| | Change |
|---|---|
| I-9 | Dimension is a stored property of the corpus. States that the embedder is not pluggable the way a generation model is; replacing it is a re-embed behind a migration |
| I-16 | "Prioritize Ollama" → a fresh install works with no account, key or network |
| I-27 | One context window per loaded model, resolved from the model. A 256K capability is not a budget |
| I-28 | Rationale is portability, not "a small local model does not infer a pedagogy". Names the guard's gap: `flashcard_prompts.py` still enumerates Bloom levels |
| I-31 | Heading generalised to "the runtime's serving width" |

Warranted but not yet written, because each needs its guard first:

| Rule | Phase | Guard |
|---|---|---|
| Model choice resolves through the registry; no service reads a model name from config | 3 | Config-read test |
| A compensation for model behaviour is a typed, attributed, expiring accommodation — never an invariant, never an inline prompt string | 4 | Render-path guard |
| Background LLM work yields to interactive work | 5 | Yield test + latency gate |
| A memory profile constrains the role→model map | 7 | Residency test |
| I-31: collapsing roles spends text/vision isolation | 7 | Lands with the collapse |
