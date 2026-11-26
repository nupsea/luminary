# Quiz

A multiple-choice quiz written from the learner's own documents: single-answer (radio) and
multi-answer (checkbox) questions, at a level that sets how close the wrong options sit to the
truth. Backend only so far; the screens follow the approved prototype.

Code lives in `services/quiz_builder.py` (writing items), `quiz_parsers.py` (the structural
gates), `quiz_prompts.py`, `quiz_scoring.py` (pure), `quiz_service.py` (the lifecycle),
`repos/quiz_repo.py` and `routers/quiz.py`.

## Tables

| Table | Holds |
|---|---|
| `quizzes` | scope (`document` / `chapter` / `section` + id), level (`easy` / `medium` / `hard` / `adaptive`), `mode` (`practice` / `exam`), kinds, `status` (`building` / `ready` / `complete` / `error`), its `study_sessions` row (mode `quiz`), `retake_of` |
| `quiz_items` | the bank: stem, kind, level, `section_id`, `source_chunk_ids` (I-35), `flashcard_id` when the item tests a card, the writing `model`, `origin` (`model` / `cards`), `support_check` |
| `quiz_options` | text, `is_correct`, `explanation`; a right option's verbatim `evidence_quote`; a wrong option's `trap` and `key_similarity` |
| `quiz_questions` | which item a quiz asks at each position, and the option order it shows |
| `quiz_attempts` | one answer per question: picks, `confidence` (`sure` / `think` / `guess`), `outcome`, `score`, `time_ms` |

Deleting a document deletes its quizzes and items, and with them their options, questions and
answers (I-63). Deleting a card only unties the items that tested it. Items are reused: a quiz takes unanswered bank items
at its level and kind before it calls a model, so a second quiz on a chapter starts at once.

## Writing an item

Code decides; the model writes JSON (`{question, options: [{text, correct, quote | mistake, why}]}`).

- **Passage:** consecutive chunks of one section, 300 to 2,400 characters. Material no item was
  written from comes first, sections with the most missed answers and card lapses first among it.
- **Kind and counts:** single = 4 options, 1 right; multi = 5 options, 2 or 3 right. A mixed quiz
  asks every third question as multi.
- **Level**, described by what the wrong options do, never named (I-28):

| Level | Wrong options | Mistake codes offered |
|---|---|---|
| easy | same subject, rejected at once by anyone who read the passage | `neighbour` |
| medium | plausible claims the passage does not make; one a common misunderstanding | `belief`, `broader`, `neighbour` |
| hard | a passage statement with one decisive detail changed | `detail`, `swap`, `condition` |

The codes map to the stored `trap` set: `near_miss_detail`, `swapped_relation`, `wrong_condition`,
`overgeneralised`, `related_but_different`, `common_misconception`.

- **Adaptive** starts at medium; two right in a row go up a level, one miss (wrong or partial)
  goes down, which settles near 71% correct (three in a row would settle near 79%). The next
  question is written after the answer before it, so the staircase is real.
- **One write and two rewrites per question**, each on the next passage. A question that cannot be
  written ends the quiz there, and `question_count` says so.
- **Without a model**, single-answer items are assembled from grounded cards in the scope, with
  three other cards' answers as the wrong options: `origin='cards'`, always `easy`.

## Gates

Each refusal is a named kind, logged and counted as `quiz_reject_<kind>` (`GET /evals/output-stats`).

| Kind | Refuses |
|---|---|
| `unparsed` | no JSON object, no question or no options |
| `shape` | a stem that is not a question; option or right-option counts other than asked; a right option without a quote; a wrong option without a known mistake code; an option that is the prompt's placeholder |
| `ungrounded` | a right option's quote not verbatim in the passage (I-34's matcher and 12-character floor) |
| `wrong_option_stated` | a wrong option of five or more words copied from the passage |
| `points_at_source` | a stem that needs the passage in view (I-50's rule) |
| `giveaway` | "all / none of the above", or an option naming other options |
| `right_is_longest` | single-answer: the right option over 1.6 times the longest wrong one |
| `duplicate_options` | two options with the same text, or embedding cosine of 0.95 or more |
| `right_option_unsupported` / `wrong_option_supported` | the factuality judge rejects a right option or accepts a wrong one |
| `off_level` | a wrong option outside its level's similarity band. Off: cosine does not separate the levels (below) |

The judge is `FLASHCARD_FACTUALITY_MODEL`, never the writer (I-85). It is given the stem and told it
judges one option alone: asked about a bare option, it rejected fragments that mean something only
under their stem, and against a "which of these" stem it read one true option as a partial answer.
Without a judge, items are `support_check='unchecked'` and wrong options are checked only
structurally.

## Scoring and the learner record

- Single: right or wrong. Multi: `max(0, (hits - false picks) / right options)`; `correct` only
  for the exact set, `partial` above zero.
- A miss or partial answer on an item tied to a card rates the card `again`; a right answer
  writes nothing (I-84). A confident miss opens a misconception.
- Practice mode reveals each option (explanation, quote, trap) after its answer; exam mode only
  after the finish. A multi question shows how many to pick, except at hard.
- Results: score, calibration per confidence, which traps were shown and picked, sections with
  misses. A retake asks the misses, the partial answers and the right guesses again.

## API

| Route | Does |
|---|---|
| `POST /study/quizzes` | create; 201 while `building`. A chapter or section outside the document is 404 (I-70) |
| `GET /study/quizzes/{id}` | the quiz, the questions written so far, `results` once complete |
| `POST /study/quizzes/{id}/answers` | one answer per question (409 on a second); feedback in practice mode |
| `POST /study/quizzes/{id}/finish` | complete it, end its session, return the results |
| `POST /study/quizzes/{id}/retake` | a new quiz of the misses and guesses |
| `POST /study/quiz-items/{id}/to-card` | a grounded card from a single-answer item; 409 if it has one, 422 for a multi item or a stem that needs its options |

## Measured

2026-11-26, a copy of the dev library, writer `ollama/qwen3.5:4b`, judge
`ollama/qwen2.5:14b-instruct`, DDIA and Moby-Dick, 6 questions per level, mixed kinds.

| | |
|---|---|
| Writes | 156, all parsed first time; 20 accepted (13%) |
| Refused by | source-pointing stem 56 (24 of them "the narrator", Moby-Dick), judge rejects a right option 36, shape 21, ungrounded quote 15, judge accepts a wrong option 4, unparsed 2, identical options 2 |
| Never fired | `wrong_option_stated`, `giveaway`, `right_is_longest` (right option at most 1.06 times the longest wrong one), the 0.95 cosine duplicate |
| Built of 6 | DDIA 6 at every level; Moby-Dick 1 easy, 2 medium, 4 hard before the call budget ran out |
| First question | 82 to 96 s when nothing was banked, 2 s from the bank; 4 to 8.5 min for 6 |
| Wrong-option cosine, median | easy 0.645, medium 0.601, hard 0.610: the levels do not separate |
| Right answer as shown | positions 6, 2, 5, 4 over 17 single items; the longest option in 2 of 17 |

Read by hand, the accepted items are on topic and quoted, but many hard items have wrong options
that are absurd rather than one detail off, and one wrong option was true (DDIA recommends t-digest
for rolling percentiles; the judge passed it). The stem and judge framing above came after this run;
15 further writes are too few to say what they changed.

Not measured: the people-rated gate (6 in 10 items kept, on two runs, the reason for each
discard). Quiz is not on by default until it passes.
