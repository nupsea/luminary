# Quiz quality: Mac Studio handoff

Context for the next stage of the quiz work (PR #572, branch `feature/quiz-engine`), which runs on
the Mac Studio because the office laptop cannot download models. Start here.

## What is where

| What | Where | How it gets to the Mac Studio |
|---|---|---|
| Quiz code | branch `feature/quiz-engine`, head `2a599915`, CI green | `git fetch` |
| This folder: scripts, results, Claude's verdicts | branch `chore/quiz-mac-studio-handoff` (orphan; never merged, no PR) | `git fetch` |
| Verify library, vectors, and the files that quote the books | `lm-quiz-handoff-2026-11-28.tar.gz` on the laptop | the user copies it |
| The user's choices for this stage | artifact https://claude.ai/artifact/9KyoJCfr3bcEohMTyDpqqS, doc `handoff/inputs`; snapshot in `inputs.json` | read it with ArtifactData `get`; the live doc wins over the snapshot |

The repo is public. Passages from DDIA are O'Reilly's copyrighted text, so nothing that quotes a
passage is committed: `.gitignore` lists those files and they travel in the archive.

## The user's choices (saved 2026-11-28)

- **Machine:** M4 Max, 64 GB. Ollama **shared**: warn the user before every model run and stop
  when they say so. Downloads from Ollama and Hugging Face are allowed there.
- **Writers:** `qwen2.5:14b-instruct` (baseline) and `qwen3:14b`, plus "anything that can run within
  a 16 GB laptop comfortably". **The 16 GB laptop is the product's target**: a writer that only a
  64 GB machine runs is not a candidate, however good.
- **Judge:** `gemma4:latest` only. The writer must be from another family, so no Gemma writer.
- **NLI:** `facebook/bart-large-mnli` (current) against `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`
  and `cross-encoder/nli-deberta-v3-small`.
- **Runs:** DDIA medium, DDIA hard, Moby-Dick medium, Federalist medium; 5 questions asked per
  quiz; 2 runs per writer; any time.
- **If a writer clears the bar:** publish its questions for the user to rate (below).
- **Pushes** to `feature/quiz-engine` are allowed: author `nseaup <eanups@yahoo.com>`, `-s` (DCO),
  pushed with the `nupsea` account. Never merge.
- **Research** (the user's note, verbatim): "Important to research if there are better strategies
  and models out there to make this whole study pipeline better. We could make use of decision
  based models or some other machine learning/transformer or suitable models at different stages
  to optimally arrive at better questions and answers with options that'll help all the three
  facades (quiz, flashcards and teach back)". See "Research".

## Where quality stands

- **Bar before the user rates anything:** at least 8 in 10 accepted questions kept by Claude's
  review on two independent runs, and no wrong option the material makes true. The user's own
  gate is 6 in 10.
- **Runs 8 to 11, qwen2.5:14b writing:** 21 of 44 kept (58%, 55%, 20%, 55%); 3 true wrong options
  in 4 runs. Per-run rows in `results.md`; every verdict, with its reason, in
  `partial/verdicts_runN.json` (keyed by item id; the items are in the archive).
- **What still fails** is the writer's phrasing, which no check fixes without refusing good
  questions:
  - a right answer that garbles or narrows its sentence;
  - a wrong option as close to the text as the right one, or a paraphrase of a nearby sentence;
  - two wrong options making one claim; a wrong option that is a right one plus "is optional";
  - trivial key sentences ("humans build software"); "a homeless person" for Lazarus.
- **Tried and not adopted** (measurements in `results.md`): cosine or mutual NLI for repeated
  claims; a judge given the nearest chunks; refusing two-part stems (2 of 5 were good);
  bespoke-minicheck as the entailment step (true options 0.01 to 0.67, reversals up to 0.94).

## How to review

The review is the measurement, so it gets no shortcuts (the user's words: "don't take shortcuts in
evaluating"):

- Read every accepted question against its **whole passage**, not the key sentence alone. Run 8 read
  against key sentences only scored 10 / 2 / 0; read against the passages it was 7 / 4 / 1.
- Check every wrong option for truth **anywhere in the book**, not only in the passage.
- Verdicts: **keep**, **fix** (salvageable with an edit), **drop** (a true wrong option, or
  worthless). Write `partial/verdicts_runN.json` as `{item_id: [verdict, why, tags]}` and add a row to
  `results.md`.
- A number that looks too good (a 100% keep, two writers identical) is a harness bug until shown
  otherwise. Runs 1 to 9 ran with an empty vector table and nothing reported it.

## The pipeline (v2)

1. **Passage.** Chunks are joined without their overlap. A contents page, licence, quotation
   collection or reference list is refused (`quiz_material.unfit_reason`).
2. **Key sentences.** Code picks what a question tests. Single-answer: a whole sentence (never a
   question, numbered note or sentence about the book itself), among the eight longest, dropping
   those more than 0.15 below the closest to the section summary, then the longest
   (`quiz_material.pick_keys`). Multi-answer: 2 or 3 items of one list and its opening line
   (`pick_list`).
3. **Question call.** The writer phrases one question about the key. Refused if the answer covers
   less than 0.5 of the key's content words, names someone the passage doesn't, points at its
   source ("according to the story", "mentioned", "the text uses"), says "someone" for a named
   subject, or is stated in the stem. A refused question is retried once with the reason.
4. **Wrong-answer call.** 6 slots (single) or 6 to 7 (multi), each with a mistake type code assigns.
   Dropped if copied from the passage; absolute where the right answer isn't; outside 0.5 to 1.8
   times the right answer's length; first person where no right answer is; an echo of a list item
   the question leaves out (0.4 of its content words, stem words removed); or entailed at 0.8 or
   more by the passage or by the document's five nearest chunks. A document with no vectors is
   counted (`quiz_drop_elsewhere_unsearched`).
5. **Judge.** `FLASHCARD_FACTUALITY_MODEL`, never the writer, answers with the passage and must pick
   exactly the right answers.
6. **Guess.** `QUIZ_GUESS_MODEL` answers without the passage in three shuffled orders. Right all
   three times refuses the question at medium and hard.

## Set up on the Mac Studio

1. In the Luminary checkout:
   ```sh
   git fetch origin feature/quiz-engine chore/quiz-mac-studio-handoff
   git worktree add ../lm-quiz-engine feature/quiz-engine
   git worktree add ../lm-quiz-verify-scripts chore/quiz-mac-studio-handoff
   ```
2. Unpack the archive from the laptop: `tar -xzf lm-quiz-handoff-2026-11-28.tar.gz -C ~/DEV/LM`.
   It holds `lm-quiz-verify-data/` (the library: `luminary.db`, `vectors/`) and the ignored files of
   `lm-quiz-verify-scripts/` (`partial/items_run*.json`, run reports and logs).
3. Models. The library's `models/` folder is empty in the archive. Link the Mac Studio's own
   Luminary models into it (`bge-m3`, `bge-small`, `gliner`, `ms-marco-minilm*`), the way the laptop
   did, and fetch the NLI models once with `HF_HUB_OFFLINE=0` into `models/<slug>/`.
4. A backend venv in the Luminary checkout (`make install-dev`). Never `uv sync` from the worktree;
   it shares the main venv.
5. Check the vectors before the first run. Each document's vector count must equal its chunk
   count (DDIA 3355, Moby-Dick 2931, Federalist 2537). An empty table makes `wrong_true_elsewhere`
   pass everything without a word.
6. Pull the writers. Read each model's licence before it goes anywhere near something that ships
   (I-71).

## Run a build

```sh
cd ~/DEV/LM/lm-quiz-engine/backend
DATA_DIR=~/DEV/LM/lm-quiz-verify-data HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  LITELLM_GENERATION_MODEL=ollama/<writer> FLASHCARD_FACTUALITY_MODEL=ollama/gemma4:latest \
  QUIZ_GUESS_MODEL=ollama/qwen3.5:4b OMP_NUM_THREADS=4 PYTHONPATH=. \
  nice <venv>/bin/python ~/DEV/LM/lm-quiz-verify-scripts/run_build.py 5 <out>.json \
  DDIA:medium,DDIA:hard,moby-dick:medium,federalist:medium
cd ~/DEV/LM/lm-quiz-verify-scripts
python3 review_export.py ~/DEV/LM/lm-quiz-verify-data/luminary.db <out>.json <out>.md
PYTHONPATH=~/DEV/LM/lm-quiz-engine/backend <venv>/bin/python export_items.py \
  ~/DEV/LM/lm-quiz-verify-data/luminary.db <out>.json partial/items_<run>.json
```

- **Empty the quiz tables before each run**, or unanswered questions from the last run are served
  from the bank and nothing new is written. First copy `luminary.db` to
  `luminary-after-<run>.db` and check the copy holds the quiz rows; only then clear the tables.
- Warn the user before each run (Ollama is shared). One heavy job at a time.
- A run on the laptop took 40 to 70 minutes.

## What to evaluate

| Question | Candidates | Decided by |
|---|---|---|
| Writer | `qwen3:14b` against `qwen2.5:14b-instruct`; then others that fit 16 GB beside the judge, from a family other than Gemma (check the tags exist before pulling: `qwen3:8b`, qwen3.5 at 14B or under, `phi4:14b`, `mistral-nemo:12b`, `llama3.1:8b`, `granite3.3:8b`) | review keep rate and true wrong options on two runs; also wrong options dropped per question, answers off their key, first-question latency |
| NLI model | the two DeBERTa models against `bart-large-mnli` | `nli_bracket.py`: a threshold that drops all 3 true options and no false one, on the 127 reviewed wrong options of runs 8 to 11 |

- On a 16 GB laptop the writer (about 9 GB at 14B), the judge (`gemma4:latest`, 9.6 GB) and the
  guesser cannot all stay loaded, so Ollama swaps between calls. Measure residency with Ollama's
  `/api/ps`, never process RSS (I-39), and report the latency a 16 GB machine would see, not only
  the Mac Studio's.
- `nli_bracket.py <repo_id> <cache_dir> <out.json>`, from this folder with `DATA_DIR` set and the
  quiz worktree on `PYTHONPATH`. Reference numbers for bart-large-mnli are in `results.md`
  ("NLI bracket"). `ENTAILED = 0.8` in `quiz_nli.py` is measured for bart only; another model
  needs its own two brackets: wrong options as here, and right answers against their key (clean
  paraphrases against answers that add a claim; v2 run 3 in the archive).

## Research

The user asked for a survey of better strategies and models across the study pipeline, for all
three surfaces: quiz, flashcards and teach-back. Do it before spending many runs on writer
comparisons; it may change what is worth comparing. Report it as a recommendation with evidence
(papers, licences, sizes, whether it runs on a 16 GB laptop), then measure the promising ones on
this harness. Questions to answer, by stage:

- **What to test** (key selection): trained models for picking the sentence or concept worth a
  question (answer-aware selection, keyphrase or importance models) against "longest sentence near
  the summary". Trivial keys are a recurring drop.
- **Question writing:** question-generation models fine-tuned on reading-comprehension sets against
  a general instruct model; whether a small fine-tuned model plus the current checks beats a 14B
  instruct model.
- **Wrong options:** distractor-generation models and distractor *ranking* (a learned scorer of
  plausible-but-false), so the writer proposes many and a model picks. This targets giveaway and
  repeated wrong options.
- **Checking:** question-answering consistency (answer the generated question with an extractive QA
  model over the passage and compare with the key) for garbled or narrowed right answers; NLI
  models that handle paraphrase better, for the true-wrong-option miss.
- **Decision layer** (the user's "decision based models"): a learned accept/refuse classifier over
  the signals already computed (entailment scores, guess results, judge agreement, length and
  overlap features), trained on the reviewed verdicts (44 items now, more each run), instead of
  hand-set thresholds. Say how many labelled items it would need.
- **Flashcards and teach-back:** which of the above carry over. Flashcards share the
  `flashcard_parsers` checks; teach-back grading compares answers, where QA and NLI models apply.

Rules that still hold: everything runs locally by default; all LLM calls go through LiteLLM; read
each model's licence before proposing it (copyleft needs the maintainer); no corpus-specific
examples in prompts or code.

## If a writer clears the bar

1. Export each passing run (`export_items.py`), then merge them with Claude's verdicts:
   `python3 page_items.py rating-page-v2/items.json <label>:partial/items_<run>.json:partial/verdicts_<run>.json ...`
2. Publish `rating-page-v2/` (it stores ratings with the `db` capability: pass
   `capabilities: {db: {}}` and an icon on the first publish) and send the user the link. The user
   rates before seeing Claude's verdict.
3. Below the bar, report the numbers plainly. Never call #572 done below the bar.

## Before pushing to #572

Update the "Measured" section of `docs/quiz.md` with the new runs; run `make ci` (check
`~/code/papercuts.md` first; a crashed Windows xdist worker in an unrelated test is a known flake:
re-run the failed job); commit as above; watch CI to green.
