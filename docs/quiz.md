# Quiz

A multiple-choice quiz written from the learner's own documents: single-answer (radio) and
multi-answer (checkbox) questions, at a level that sets how close the wrong options sit to the
truth. Backend only so far; the screens follow the approved prototype.

Code lives in `services/quiz_builder.py` (writing items), `quiz_material.py` (passages and key
sentences, pure), `quiz_parsers.py` (the structural gates), `quiz_nli.py` (entailment),
`quiz_prompts.py`, `quiz_scoring.py` (pure), `quiz_service.py` (the lifecycle), `repos/quiz_repo.py`
and `routers/quiz.py`.

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

Code picks what is tested; the model phrases it, in small calls (I-85).

1. **Passage:** consecutive chunks of one section, 300 to 2,400 characters, joined without the
   chunker's overlap. Refused before any call: a contents page, licence text, a quotation
   collection, a reference list (`quiz_material.unfit_reason`). Material no item was written from
   comes first, sections with the most missed answers and card lapses first among it.
2. **Key:** a single-answer question tests one whole sentence: never a question or a numbered
   note, among the eight longest learnable ones, those more than 0.15 below the closest to the
   section's summary dropped, then the longest. A multi-answer question tests 2 or 3 items of one
   list, with the line that introduces it; a passage with no list gets a single-answer question.
3. **Question call:** the stem and one answer per key.
4. **Wrong-answer call:** code assigns each of 6 or 7 slots its mistake type; the model fills them.
   The survivors nearest the right answers' length are kept.
5. **Judge call:** a separate model answers with the passage and must pick exactly the right
   answers, or none when the question assumes what the material does not say.
6. **Guess calls:** `QUIZ_GUESS_MODEL` (default: the background model) answers without the passage in
   three orders. Right every time refuses the question above easy; at easy it is counted.

- **Kind and counts:** single = 4 options, 1 right; multi = 5 options, 2 or 3 right. A mixed quiz
  asks every third question as multi.
- **Level**, described by what the wrong options do, never named (I-28):

| Level | Wrong options | Mistake codes offered |
|---|---|---|
| easy | same subject, rejected at once by anyone who read the passage | `belief`, `broader` |
| medium | believable to someone who half-remembers it; the material shows them wrong | `belief`, `broader`, `condition` |
| hard | the right answer or another statement with one decisive detail changed | `detail`, `swap`, `condition` |

No level offers `neighbour` (true of something else the material discusses): as a statement it is
true. The codes map to the stored `trap` set: `near_miss_detail`, `swapped_relation`,
`wrong_condition`, `overgeneralised`, `common_misconception`, and `related_but_different` for
items assembled from cards.

- **Adaptive** starts at medium; two right in a row go up a level, one miss (wrong or partial)
  goes down, which settles near 71% correct (three in a row would settle near 79%). The next
  question is written after the answer before it, so the staircase is real.
- **Three passages per question**, each tried once. A question that cannot be written ends the
  quiz there, and `question_count` says so.
- **Without a writing model**, single-answer items are assembled from grounded cards in the scope,
  with three other cards' answers as the wrong options: `origin='cards'`, always `easy`. Without the
  entailment model (`QUIZ_NLI_MODEL`, fetched on request) the model writes nothing.

## Gates

A question is refused whole (`quiz_reject_<kind>`); a wrong answer is dropped alone
(`quiz_drop_<kind>`), and the question refused when too few survive. Both at `GET /evals/output-stats`.

| Question refused | When |
|---|---|
| `unparsed`, `shape` | no JSON; a stem that is not a question; answer count other than asked; the prompt's placeholder |
| `points_at_source` | the stem needs its source in view (I-50's rule), or credits "the story", "the discussion" |
| `invented_name` | the stem names someone the passage never does |
| `why_without_reason` | a "why" stem over keys that give no reason |
| `count_in_stem` | a multi-answer stem with a number in it |
| `other_script` | an answer in a script the passage does not use |
| `answer_in_stem` | the stem carries 80% of an answer's content words |
| `answer_off_key` | an answer no key sentence entails at 0.8 (each key used once) |
| `too_few_wrong` | fewer wrong answers survived than the kind needs |
| `right_is_longest` | single-answer: the right answer over 1.25 times the longest wrong one |
| `duplicate_options` | embedding cosine of 0.95 or more between two options |
| `not_answerable` | the judge picks other than exactly the right answers |
| `guessable` | right without the material in all three orders, above easy |

| Wrong answer dropped | When |
|---|---|
| `wrong_stated` | copied verbatim from the passage |
| `wrong_absolute` | always, never, only, all, every, completely, entirely, none, solely or universally, when no right answer uses one |
| `wrong_length` | under 0.5 or over 1.8 times the right answers' mean length |
| `wrong_entailed` | the passage entails it at 0.8 |
| `wrong_true_elsewhere` | one of the document's five nearest chunks entails it at 0.8 |

The entailment threshold is bracketed twice, with `facebook/bart-large-mnli` on CPU: true "wrong"
options scored at least 0.84 and false ones at most 0.68 (25 items, 101 options); clean paraphrase
answers at least 0.90 and answers adding a claim at most 0.46 (92 answers). Another model needs
its own brackets.

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

2026-11-27, a copy of the dev library, writer `ollama/qwen2.5:14b-instruct`, judge
`ollama/gemma4:latest`, guesser `ollama/qwen3.5:4b`; DDIA medium and hard, Moby-Dick medium,
Federalist Papers medium; 4 questions asked of each. Reviewed by reading each accepted question
against its passage.

| Run | Accepted | Keep / fix / drop |
|---|---|---|
| 4 | 12 | 7 / 4 / 1 |
| 5 | 9 | 4 / 2 / 3 |
| 6 (summary-ranked keys) | 6 | 4 / 2 / 0 |

- No accepted question in runs 4 to 6 had a wrong option the material makes true.
- Fixable: stems that lose their subject or credit their source, trivia, recall of a whole list.
  Dropped: an editorial note asked twice, an aside read as fact, one right answer that reversed
  its sentence's logic (neither entailment nor the judge caught it).
- Most frequent refusals per run: guessable 18 to 25, points_at_source 20 to 23, answer_off_key 10
  to 14; drops: wrong_absolute about 50, wrong_entailed 25 to 46.
- First question 44 to 420 s with nothing banked; 6 to 12 questions per 35-minute run.

The bar before people rate a sample is 8 in 10 kept on two runs; the people-rated gate is 6 in 10.
Neither is met, and Quiz is not on by default.
