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

**`paper` was not fit to gate on, and was regenerated 2026-08-12.** `art_of_unix.txt` is a
scrape of the ibiblio edition carrying that site's chrome interleaved with the prose — 460 of
2166 lines, 118 of 248 chunks. 17 of 40 golden questions asked about the chrome rather than the
book, and 18 of 40 hints matched more than one passage, 17 of them five or more, so a hit was
credited for retrieving any of eight identical nav blocks. The floor had been lowered to
0.45/0.30 instead of the data being fixed.

Fixed in ingestion, not in the corpus: `app/services/source_text.py` collapses repeating
furniture, and `generate_golden.py` reads its source through it so the generator and ingestion
see one document. **Do not truncate** — 1105 words of real prose sit past the apparent seam at
line 1734, including "Part III. Implementation".

| | before | after |
|---|---|---|
| chrome-sourced questions | 17 / 40 | **0** |
| ambiguous hints | 18 / 40 | **2** (one phrase the book prints twice) |
| distinct hints | 32 | 39 |
| index | 248 chunks | 146 chunks |
| document tags | included `terasaur` | `unix-philosophy`, the Rule-of-X concepts |
| MRR across re-runs | drifted 0.0125 | bit-identical |

Measured after regeneration, one library state: `paper` 0.850 / 0.703 / 0.746,
`book` 0.575 / 0.398 / 0.507. `paper` now carries the default floor.

**The before and after numbers are not comparable** — different questions against a different
index, and a 146-chunk haystack is mechanically easier than 248. What is established is that
the dataset now measures the book, and that the measurement is reproducible.

**A corpus change can re-rank an untouched document.** Re-ingesting `paper` moved `book`'s MRR
from 0.4104 to 0.3979 with nothing about `book` touched, both values bit-reproducible on either
side. That is the same magnitude as the entity-model difference measured on `paper`, so **that
difference was indistinguishable from a library-state change**.

The coupling is not universal and its mechanism is **not established**: ingesting three further
documents (~4,870 chunks) moved `book` and `paper` by zero. Two candidates sit in the code and
neither has been isolated — `bm25(chunks_fts)` scores over the whole FTS table with the
`document_id` filter applied to matched rows (`retriever.py:225`), and graph expansion reads an
entity graph that every ingest rewrites. The operational rule holds either way: re-run the
baseline arm after any corpus change instead of comparing against an earlier number.

Every document kind under DATA now has a golden, generated 2026-08-12 with the same
generator/verifier/axes as the rest so provenance stays comparable. All are structurally clean:
every hint resolves and identifies exactly one passage, every row graded.

| dataset | source | rows | flagged | chunks | HR@5 / MRR / nDCG |
|---|---|---|---|---|---|
| legal | federalist_papers.txt | 60 | 0 | 2537 | 0.533 / 0.373 / 0.451 |
| play | hamlet.txt | 60 | 5 | 394 | 0.650 / 0.441 / 0.526 |
| study | sutton_barto_rl.pdf | 60 | 17 | 1939 | 0.583 / 0.414 / 0.483 |
| thoughts | daily_thoughts_2026.txt | 4 | 0 | 7 | 1.000 / 1.000 / 1.000 |

`study` is the first measurement of the **PDF parse path**, which no eval reached before —
`generate_golden.py` read sources as bytes, so a PDF produced questions about
`%PDF-1.5 /FlateDecode`. It now reads through `universal_parser.read_document_text`.

`thoughts` reads 1.000 on every metric because top-5 retrieval over a 7-chunk document returns
most of the document. That is a property of a 2,944-char source, not of retrieval, and it is
why the dataset is measured but never gated. `make eval` covers the other five.

## Generation quality — first measurement

`make eval` never called the answering path: `--judge-model` defaults to empty, so no `/qa`
ran, every generation metric was `None`, and the Quality UI showed `-` in those columns for
every one of 285 recorded runs. `make eval-gen` exercises the shipped path and asserts.

Measured 2026-08-12, `ollama/qwen2.5:14b-instruct` judge, one library state, 0 judge failures:

| | book | paper |
|---|---|---|
| faithfulness (HHEM) | 0.678 | 0.626 |
| answer_relevance | 0.706 | 0.852 |
| **citation_support_rate** | **0.485** | **0.400** |
| citation_coverage | 0.750 | 0.872 |
| answer_rate | 0.900 | 0.975 |
| declined (not_found) | 4 / 40 | 1 / 40 |

0.485/0.400 is not a clean read of citation quality. Measured over the chips behind it, the
number is two independent defects stacked, and the metric moved in both directions at once.

**The product defect is fabricated quotes, not weak support.** Of 6 chips across 10 `book`
questions on 0.6.1, 3 quoted text absent from the answer's grounding: the model's own narration,
commentary about the retrieval ("The context does not provide specific details about..."), and
one real passage retrieval never returned. Closed by I-33 — excerpts are verified against the
grounding and dropped when absent, and every citation-bearing prompt now requires a verbatim
excerpt. After the fix 5 of 5 surviving chips are verbatim, and the filter dropped exactly one
chip across 10 questions (a paraphrase), so it is not over-dropping.

**The metric mis-scored in both directions.** It judged each excerpt against the whole answer
under a prompt demanding the citation "fully supports the claim", which no single excerpt can
do: it scored `no` on a verbatim correct citation and `partial` on two more, while giving the
fabricated commentary chip a `yes`. The prompt now asks whether the chip supports at least one
claim the answer makes — 0.500 vs 0.750 on identical chips. **Scores recorded before this change
are not comparable to scores after it.**

### Post-I-33 baseline

Measured 2026-08-13, same judge, 0 judge failures and 0 `/qa` failures on either dataset.
Retrieval came back bit-identical to the recorded baselines (book 0.5750/0.3979/0.5074, paper
0.8500/0.7025/0.7461), so the library state matches the run above and the generation-side
comparison is meaningful.

| | book | paper |
|---|---|---|
| faithfulness (HHEM) | 0.6446 | 0.6729 |
| answer_relevance | 0.6326 | 0.8855 |
| citation_support_rate | 0.7286 | 0.8061 |
| **citation_coverage** | **0.5429** | **0.7632** |
| answer_rate | 0.8750 | 0.9500 |
| declined (not_found) | 5 / 40 | 2 / 40 |

`make eval-gen` fails: book on citation_support_rate and citation_coverage, paper on
citation_coverage.

**Coverage fell on both datasets, and the excerpt filter is not what caused it.** It dropped 2
citations across all 80 questions. The cause is the prompt: instructed to leave the list empty
rather than invent an excerpt, the model now declines to cite at all on a large share of answers
(book 27/36 answers carrying a chip before, 19/35 after). Trading a fabricated quote for no
quote is the right direction, but trading a *findable* quote for no quote is not, and that is
what the coverage drop mostly is.

### Marker citations — the standing baseline

The model no longer transcribes anything. `pack_context_indexed` labels each emitted passage
`[S<n>]`, the model cites `{"source":"S1"}`, and the backend fills the excerpt from that chunk —
verbatim by construction, and carrying the `chunk_id` that makes the chip deep-linkable. Chips
are then ranked by retrieval score, gated on relevance and capped at `MAX_CITATIONS`, the same
policy `source_citations` has always used.

The excerpt shown is the part of the chunk that bears on the answer, not its head. That last
point was worth 0.18-0.29 of citation_support_rate on its own.

Measured 2026-08-13, same judge, retrieval bit-identical to every row above. **Compare future
changes against this table.**

| | book | paper |
|---|---|---|
| faithfulness (HHEM) | 0.6855 | 0.7012 |
| answer_relevance | 0.6729 | 0.8527 |
| **citation_support_rate** | **0.6754** | **0.7449** |
| citation_coverage | 0.8571 | 0.9744 |
| answer_rate | 0.8750 | 0.9750 |
| citations proposed / gated / dropped | 63 / 6 / 0 | 49 / 0 / 0 |

**citation_support_rate spent this whole investigation measuring the excerpt window rather than
the citation.** The metric judges the text the chip displays, and that text was cut from the head
of the cited chunk: 12 of 15 `book` chips were head cuts. Judged on their full chunk instead, the
same chips scored **0.8667 against 0.5667** for the displayed excerpt, with 8 of 15 verdicts
flipping and none flipping the other way — and **zero `no` verdicts** on the full chunks. The
model's source selection was never the defect; it picks a passage that supports the answer ~87%
of the time. Selecting the window against the answer instead of taking the head moved support
0.5000 -> 0.6754 (book) and 0.4500 -> 0.7449 (paper) with retrieval, prompt and proposals
unchanged.

Two structural fixes were spent on the wrong hypothesis before this was measured. The cap almost
never binds (~1.5 chips per answer) and the relevance gate removed 0 of 49 chips on `paper`;
neither could have moved a number that was reporting a windowing artifact. The lesson is the
metric's own: **judge what the product shows, and confirm the metric is scoring the object you
think it is before optimising against it.**

See
I-33. `make eval-gen` has not yet been re-run against this design, so the numbers above remain
the standing baseline and the floors stay untouched: one measurement per dataset is not a
distribution, and a bar set now would be calibrated against a design that has already changed.

`citation_support_rate` had never once computed, for two independent reasons that each hid the
other: it paired claims by splitting prose on `[N]` markers the product never emits (it returns
prose plus a JSON citations block), and `judge_citation` imports `litellm`, absent from the
`evals` project so every call raised `ModuleNotFoundError` into a swallowed counter. I-32 —
uncomputed metrics fail rather than pass — is what surfaced both.

### Variance, and the floors derived from it

Four runs per dataset on one frozen build, same corpus, bit-identical retrieval:

| | citation_support_rate | citation_coverage | answer_rate | faithfulness |
|---|---|---|---|---|
| book | 0.6491 ± 0.0521 | 0.8245 ± 0.0628 | 0.9250 ± 0.0354 | 0.6888 ± 0.0120 |
| paper | 0.7089 ± 0.0254 | 0.9679 ± 0.0323 | 0.9750 ± 0.0000 | 0.6802 ± 0.0168 |

**A single run cannot resolve a change smaller than ~0.10 on book or ~0.05 on paper.** book's
support rate ranged 0.5893–0.7065 across identical runs, and `citations_proposed` ranged 49–71:
the model's citation volume is itself unstable, which is most of the spread. Two structural
changes were credited with moving this metric by less than that band; both were inside the noise
and neither claim survives. Compare distributions over repeated runs, never two points. Retrieval
metrics are exempt — they are bit-reproducible on a fixed corpus.

The generation floors are now `mean - 3sd` for the weaker dataset, rounded down to 0.05:
`citation_support_rate` 0.45, `citation_coverage` 0.60, `answer_rate` 0.75. They replace 0.80s
that were invented with no derivation. They are collapse detectors and say nothing about quality:
support at 0.65 is not good, it is what this build scores, and the number to beat is the measured
mean rather than the floor.

`citation_coverage` is measured post-I-33 above. What is still unmeasured is the split between
the two reasons an answer carries no chip — the model emitted none, or the filter removed one —
because the eval cannot see drops. Two runs put the filter at 2 of 80, so the split is currently
inferred from a backend log rather than recorded. Surfacing a per-response drop count under
`include_context`, the same eval-only precedent as `context_chunks`, makes it a number instead of
an inference.

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
