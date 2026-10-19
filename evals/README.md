# Luminary eval harness

How to run Luminary's evaluations, what each run tests, and with which data and models. The full
map of what is and is not measured is `docs/eval-coverage.md`; the rules for quoting a number are in
the `eval-integrity` skill. All commands run from the repo root.

## Pick a run

| You changed | Run | Library |
|---|---|---|
| Parsing, classification, chunking, sections, indexing | `make eval-full` | fresh |
| Retrieval or ranking only | `make eval` (fast), confirm with `make eval-full` | dev, then fresh |
| Answering: prompts, `/qa`, citations, the chat model | `make eval-gen-full`; `make eval-variance` for a small effect | fresh / dev |
| Card generation: flashcard prompts, parsers, gates, the chat model | `make eval-cards-full` | fresh |
| A release against master | any `*-full` target with `EVAL_BACKEND=<release worktree>/backend` | fresh |

### Dev library or fresh library

`make eval`, `make eval-gen` and `make eval-flashcards` query the backend on :7820 and score the
documents as they were ingested, possibly months and many builds ago. **An ingestion change never
reaches them**: their numbers did not move for weeks while ingestion changed underneath.

The `*-full` targets (`scripts/eval_full.sh`) need no running backend. Each one:

1. starts its own backend on an empty temporary library (`EVAL_PORT`, default 7850);
2. pins the chat model (`EVAL_CHAT_MODEL`, default the shipped `ollama/qwen3.5:4b`) before
   ingesting, since ingestion writes chapter cards with it and a fresh library would otherwise
   use the router default;
3. uploads the whole corpus with no `content_type`, as the upload dialog does, so the pipeline
   classifies each document;
4. waits until every document is `complete`. Generation and card runs then also wait for
   background enrichment to drain: chapter cards, web references and concept links all call the
   model, and the repair and delivery counters a run reads are process-wide, so a card written in
   the background would count as a measured one. On the five corpus books that wait is hours
   (`EVAL_ENRICH_WAIT_MIN`, default 240);
5. scores, appends to `.luminary-eval/scores_history.jsonl`, and deletes the library (`KEEP=1`
   keeps it).

A fresh-library number and a dev-library number describe different corpora: compare each only
with its own history. The two are not interchangeable: on 2026-10-19, `paper` scored HR@5 0.90 on
the dev library and 0.80 fresh, because the dev library had chunked it as `paper` and a fresh
ingest classifies it as `tech_book`.

## What each run tests

### Retrieval: `make eval`, `make eval-full`

| Dataset | Source (`DATA/`) | Questions |
|---|---|---|
| `book` | `books/time_machine.txt` | 40 |
| `paper` | `papers/art_of_unix.txt` | 40 |
| `legal` | `legal/federalist_papers.txt` | 60 |
| `play` | `plays/hamlet.txt` | 60 |
| `study` | `study/sutton_barto_rl.pdf`, the only PDF | 60 |

- **The questions:** `openai/gpt-5.4` wrote each question from the source text. Each one has a
  `context_hint` copied verbatim from the passage it was written from. `openai/gpt-5.1` and
  `ollama/qwen2.5:14b-instruct` each checked that the question was answerable and the answer
  correct, and only pairs both passed were kept. Rejects are in `<dataset>.flagged.jsonl`, and the
  provenance of each dataset is in `<dataset>.meta.json`.
- **The run:** every question goes to `/search`, scoped to its document. No LLM is involved.
- **The metrics:**
  - HR@5: the hint is in the top 5 results.
  - MRR: how high the first match ranks.
  - nDCG@10.

### Answer generation: `make eval-gen`, `make eval-gen-full`

- **The questions:** the `book` and `paper` questions above. Their reference answers come from the
  same cross-verified generation.
- **The run:** each question goes to `/qa`, the answering path the app ships.
  - `eval-gen-full` answers with `EVAL_CHAT_MODEL` and asserts the backend reports it.
  - `eval-gen` answers with whatever model the dev backend has set.
- **The judge:** `EVAL_TEXT_MODEL` (default `ollama/qwen2.5:14b-instruct`) scores answer relevance
  and whether each citation supports its claim.
- **Faithfulness:** HHEM scores it with no judge.
- **Structural metrics:** answer rate and citation coverage.
- **Generation is noisy.** A single run cannot resolve a change below about 0.10 on `book`. Use
  `make eval-variance` before believing a small delta.

### Card (question) generation: `make eval-cards-full`, `make eval-flashcards`

- **The data:** `golden/flashcards_corpus.jsonl` has 30 passages, 6 from each of the five
  retrieval documents. The passages are sampled from the indexed chunks with a fixed seed, and no
  model writes any part of the golden: the passage is the ground truth every card is judged
  against.
- **The run:** each passage goes to `/flashcards/generate` and asks for 3 cards, with the pinned
  chat model.
- **Structural metrics** (deterministic, model-sensitive, and what a model swap is decided on):
  - generation rate (cards the model produced over cards asked for);
  - output repairs and first-pass rate;
  - card-gate rejections;
  - atomicity.
- **Judged metrics:** `EVAL_TEXT_MODEL` scores factuality and clarity against the passage.
- **Cards written at ingestion:** printed before the run, with the grounding state stored for each
  (`verified`, `unsupported`, `unverifiable`, `unchecked`), from `GET /flashcards/grounding`. The
  gate refuses an ungrounded card before it is stored, so this counts cards and cannot show a
  failure; the refusals are in `card_reject_ungrounded`.
- **No headroom on `qwen3.5:4b`:** atomicity and first-pass rate both read 1.0000, since the
  short-answer gate keeps every answer to one sentence and the output is schema-constrained. They
  catch a regression in those gates, not a better model.

`make eval-flashcards` runs `golden/flashcards.jsonl`, which has 35 passages over five content
kinds. Its rows name **dev-library document ids**, so it runs only against the library it was
sampled from. On that library `cards_returned` also falls on every re-run, because the
near-duplicate filter drops cards that resemble ones the document already has. A fresh library
starts with no cards, so the `cards-full` run does not have this problem.

Not covered by any target: whether a chapter card is *correct* beyond its quote being found.
`evals/card_quality/` holds a local 30B judge panel and a blind rating page for that. It is run by
hand, and its labels stay on the machine (gitignored).

## Running

```bash
make eval-full                    # retrieval, fresh library
make eval-gen-full                # answers, fresh library (hours: enrichment, then /qa + judge)
make eval-cards-full              # cards, fresh library (hours: enrichment, then 30 generations + judge)
bash scripts/eval_full.sh all     # all three on one library (needs both models in env)

KEEP=1 make eval-full                                  # keep the library to inspect it
EVAL_BACKEND=../lm-rel0161/backend make eval-full      # measure another build, same harness
make eval-gen-full EVAL_CHAT_MODEL=ollama/llama3.2     # a different answering model
```

On the company network, run with the offline environment (`HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`, `UV_OFFLINE=1` and a dead proxy). The `*-full` targets use the
embedding models already in the main checkout's `.luminary/models` and fetch nothing.

For a run against the dev backend: `make eval`, `make eval-gen` and `make eval-flashcards`
(`SKIP_JUDGE=1` gives the structural half only). `cd evals && uv run --no-sync python run_eval.py
--help` lists every flag. The ones used most:

| Flag | Does |
|---|---|
| `--dataset NAME` | a golden in `golden/` |
| `--assert-thresholds` | exit 1 when a floor is missed, or a requested metric could not be computed |
| `--judge-model M` | the judge for answer relevance and citation support |
| `--check-citations` | judge each citation against its claim |
| `--rerank` / `--no-rerank` | override the backend's shipped reranker setting |
| `--ablation` | HR@5/MRR per strategy: vector, fts, graph, rrf, rrf+rerank |
| `--max-questions N` | a deterministic sample (seed 42), for a quick look only |
| `--ingest-only` | ingest the dataset's documents and exit |

## Thresholds

The floors are `THRESHOLDS` and `DATASET_THRESHOLDS` in `run_eval.py`, and `THRESHOLDS` in
`run_flashcard_eval.py`. They are collapse detectors set from measured runs, not quality bars, and
they are never lowered to make a run pass. The flashcard floors are inherited placeholders (#160,
#226): no run has reached the 3.5 clarity floor, so an asserted card run fails on it today.

## Results

- **History files:**
  - Dev-library runs append to `evals/scores_history.jsonl`, or to `LUMINARY_EVAL_STATE_DIR` when
    it is set.
  - Fresh-library runs append to `.luminary-eval/scores_history.jsonl`.
- **What each row records:** the models, the reranker arm, and the library's document and chunk
  counts. Two rows are comparable only when those match.
- **The dashboard:** every run also posts to the backend it measured. Runs against the dev
  backend show on the Quality dashboard (`/quality`, full mode). A fresh library's dashboard is
  deleted with the library.

## Making a golden

| Golden | Target | Needs |
|---|---|---|
| retrieval / generation Q&A | `make golden-paper` (`-legal`, `-play`, `-study`, `-d2l`) | `OPENAI_API_KEY` and Ollama; sends the source text to OpenAI, so ask first |
| `flashcards_corpus` | `KEEP=1 make eval-full`, then `make golden-flashcards-corpus DB=<kept library>/luminary.db` | nothing external |
| `flashcards` | `make golden-flashcards` | the dev library |

Regenerating overwrites committed files. After a new Q&A golden, re-run the offline hint audit and
`evals/audit_golden.py` (see the `eval-integrity` skill). `RUNBOOK.md` covers generation flags and
the model matrix (`make eval-matrix`).

## Other evals

Intent routing, summaries, topics, corpus routing, chat-graph routing, refusal, false premise, note
search and ingestion fidelity each have a `make eval-*` target that runs against the dev backend.
`docs/eval-coverage.md` lists what each measures and whether it is gated.
