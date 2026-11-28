# Quiz v2 runs

Review = Claude reading each accepted question against its passage: keep, fix or drop.
"Attempts" counts question calls (one per passage tried).

| Run | Writer / judge / guesser | Scope | Accepted | Keep / fix / drop | Main refusals | Notes |
|---|---|---|---|---|---|---|
| v1 (rated set) | qwen3.5:4b / qwen2.5:14b / none | DDIA, Moby-Dick, 3 levels | 25 of 156 writes | 6 / 6 / 13 | points_at_source 56, right_unsupported 36 | 4 items had a true "wrong" option |
| v2 run 1 | qwen3.5:4b / qwen2.5:14b / writer | DDIA med+hard, Moby med | 5 | 1 / 1 / 3 | wrong_entailed 49 drops, too_few_wrong 27, answer_off_key 22 | multi stems over scattered sentences |
| v2 run 2 | qwen2.5:14b / gemma4 / qwen3.5:4b | same | 6 | 2 / 1 / 3 | answer_off_key 24, wrong_absolute 39 drops, guessable 12, right_is_longest 10 | DDIA hard good; fiction weak; Extracts quotation slipped through |
| v2 run 3 | qwen2.5:14b / gemma4 / qwen3.5:4b | DDIA med+hard, Moby med, Federalist med | 7 | 2 / 2 / 3 | answer_off_key 41 (about 25 were good paraphrases), points_at_source 19, guessable 13 | DDIA 4 of 4 usable; Moby false-premise "why" stems; Federalist 0 |
| v2 run 4 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 3 | 12 | 7 / 4 / 1 | points_at_source 20, guessable 18, answer_off_key 10, why_without_reason 6; wrong_absolute 50 and wrong_entailed 32 drops | first run with entailment key check; no true wrong option; fixable = "according to the story", trivia, list recall |
| v2 run 5 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 4 (repeat) | 9 | 4 / 2 / 3 | points_at_source 20, guessable 18, right_is_longest 17, answer_off_key 14 | run 4's gain did not repeat: runs 4+5 = 11 / 21 keep; editorial note picked twice; one right answer reversed the logic (hardware correlations) |
| v2 run 6 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 4 | 6 | 4 / 2 / 0 | guessable 25, points_at_source 23, answer_off_key 14; wrong_absolute 53, wrong_entailed 46 drops | keys ranked against the section summary; committed as ba3813a6 |
| v2 run 7 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 4 | 4 | 1 / 1 / 2 | points_at_source 39 (after 57 retries), too_few_wrong 14, guessable 14 | source rule reworded ("the learner has studied this material") + section summary + vague-subject check + one retry: the wording made the writer say "according to the material"; reverted |
| v2 run 8 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 4 | 12 | 7 / 4 / 1 | guessable 26, points_at_source 15 (after 17 retries), too_few_wrong 12, answer_off_key 11, right_is_longest 10; wrong_absolute 72, wrong_entailed 37 drops | old rule without examples, source clause cut, self-referring keys skipped, vague-subject check, one retry with the reason. First review against key sentences said 10 / 2 / 0; against full passages 7 / 4 / 1. ONE TRUE WRONG OPTION: a multi over a list, whose wrong option was an unpicked list item with one word changed. Fixes: half-true p95 option, two giveaway wrongs, two wrongs with the same claim (twice), a 'me' option |
| v2 run 9 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 4 | 11 | 6 / 3 / 2 | guessable 23, right_is_longest 18, points_at_source 12, too_few_wrong 11, answer_off_key 10; wrong_absolute 72, wrong_entailed 43 drops | run 8's pipeline plus the first-person drop and 'mentioned'. Reviewed against full passages. ONE TRUE WRONG OPTION: an open stem ('what does a firm union protect from') whose wrong option ('stops economic disputes') is Federalist No. 7's argument, missed by the nearest-chunk NLI check. One borderline list option. Drops: a trivial 'humans build software' question. Fixes: an ambiguous 'two main methods', giveaway wrong options |
| v2 run 10 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 4 + federalist medium | 10 | 2 / 7 / 1 | too_few_wrong 16, guessable 13, right_is_longest 13, points_at_source 13 (after 13 retries); wrong_absolute 54, wrong_entailed 48, wrong_true_elsewhere 13, wrong_untested_item 9, wrong_first_person 1 drops | first run with document vectors and the untested-item drop. No true wrong option. Drops: 'humans build software' again (same key sentence as run 9). Fixes: two stems 'does the text use / make' (source check lacked those verbs; added, 2 hits in 79 saved stems, 0 in 3,864 dev cards), a garbled right answer, an answer narrowed against the key with a wrong option as close, a repeated claim, two giveaway wrongs, an answer echoing its stem. Two-part stems measured as a check: 3 fix, 2 keep in the saved runs, so not added |
| v2 run 11 | qwen2.5:14b / gemma4 / qwen3.5:4b | same as run 10 (repeat) | 11 | 6 / 4 / 1 | guessable 25, right_is_longest 14, too_few_wrong 12, points_at_source 7 (after 11 retries); wrong_absolute 68, wrong_entailed 58, wrong_true_elsewhere 12, wrong_untested_item 1 drops | ONE TRUE WRONG OPTION: 'Ishmael sailed to improve his health' against 'driving off the spleen and regulating the circulation' (paraphrase NLI missed, in the passage itself). Fixes: wrong options that are right options plus 'is optional' (a form giveaway), the water/region option again (same key as run 10), 'a homeless person' for Lazarus, an unnamed 'artwork'. Runs 8 to 11 together: 21 / 44 kept (48%), 3 true wrong options in 4 runs |

## Question step alone (`question_variants.py`, 24 passages, 8 per book, qwen2.5:14b)

| Set | Wording | Pass | Notes |
|---|---|---|---|
| variants1 | old rule (with book examples) | 9 | |
| variants1 | old rule, no examples | 8 | points_at_source 10 |
| variants1 | no examples + section summary | 10 | summary brought in names the passage lacks, one misattribution |
| variants1 | run 7 rule + summary | 2 | points_at_source 16 |
| variants2 | old rule (with book examples) | 14 | after the source clause is cut and self-referring keys are skipped |
| variants2 | current: no examples, clause cut, no summary | 12 | by Claude's reading 8 to 10 of 12 good; misses: a lost subject, an answer adding a claim |

## Harness defect found 2026-11-28: runs 1 to 9 had no document vectors

The verify library's `vectors/chunk_vectors_v3.lance` was an empty table (60 KB, 0 rows); the dev
library's 106 MB table was never copied. `vector_search` returns `[]` on an empty table, so
`wrong_true_elsewhere` searched nothing and passed every option in runs 1 to 9 (it never fired).
Fixed by cloning the dev table (counts now equal chunks: DDIA 3355, Moby-Dick 2931, Federalist
2537). The empty table is kept as `chunk_vectors_v3.lance.empty-2026-11-28`. Run 10 was stopped
and restarted after the fix.

With vectors, fired on known options (`fire_elsewhere.py`): run 9's true option ("stops economic
disputes between states", Federalist No. 7's argument) scores 0.16; the run 8 list option 0.09;
false options 0.00 to 0.71. So the check would not have caught either true option: NLI does not
make the counterfactual step ("disunion breeds commercial contention" -> "union stops disputes").

## Judge variants on the 23 accepted questions of runs 8 and 9 (`judge_elsewhere.py`)

| Variant | Refuses | Of the 2 true wrong options | Good questions refused |
|---|---|---|---|
| count-free wording ("every option it shows right, however many"), passage only | 0 | 0 | 0 |
| count-free + 2 nearest chunks per wrong option | 1 | 1 (the list one, which `wrong_untested_item` now drops) | 0 |

Neither adds coverage beyond `wrong_untested_item`; not adopted. The judge agreeing on all 23 is
by construction (each passed this judge at temperature 0), so it carries no evidence.

## bespoke-minicheck on the wrong options of runs 8 to 11 (`minicheck_wrong.py`, 2026-11-28)

P(Yes) from Ollama logprobs, against the item's passage and against its 5 nearest document chunks;
127 wrong options, 3 of them true. The true ones score 0.16/0.25 (run 8 list item), 0.01/0.14
(run 9, Federalist No. 7), 0.67/0.54 (run 11, health). At 0.5 it catches 1 of 3 and drops 22 of 124
false options; at 0.8, 0 of 3 and 10. False options it rates highest are reversals ("tweets far more
numerous than reads" 0.94, "queues longer" 0.86). Not adopted: it does not separate true from false
here, and is no better than bart-large-mnli on the true ones. Scores in `partial/minicheck_wrong.json`.

## NLI bracket: bart-large-mnli reference (`nli_bracket.py`, 2026-11-28)

The 127 reviewed wrong options of runs 8 to 11, against their passage's windows and the five
nearest chunks' windows, as the pipeline scores them (passages joined with `join_chunks`; an
earlier export repeated each chunk's overlap and moved one score from under 0.8 to 0.84).

| Threshold | True caught (of 3) | False dropped (of 124) |
|---|---|---|
| 0.3 | 1 | 44 |
| 0.5 | 1 | 31 |
| 0.7 | 1 | 14 |
| 0.8 | 0 | 4 |
| 0.9 | 0 | 3 |

- True options: run 8 list item 0.72 / 0.09, run 9 Federalist No. 7 0.00 / 0.16, run 11 health
  0.09 / 0.03 (passage / nearest).
- The four false options at 0.8 or more are all from runs 8 and 9, whose nearest-chunk check
  searched an empty table. Every option of runs 10 and 11 is under 0.8 by construction: they are the
  options bart let through, so this sample favours bart, and a candidate is compared on catching
  the true ones without dropping more false ones.
