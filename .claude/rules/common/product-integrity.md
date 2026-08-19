# Product integrity is the product

Luminary's claim is that what it tells you is grounded in what you gave it. Every feature is a
promise about provenance: an answer cites chunks, a card quotes a passage, a summary reflects a
document, a metric reports a measurement. **A shortcut that makes output appear correct while
severing it from its source destroys the only thing this product sells.**

The dangerous defects are not the ones that break. They are the ones that keep working, keep
passing, and quietly stop meaning anything. Every incident below shipped or nearly shipped, and
each was found by accident.

## Never let the system satisfy its own check

A verification that the system can pass using material the system supplied verifies nothing.

**Incident (2026-08-17).** Cards must quote the source passage, and the prompt's worked example
contained a plausible-looking `source_excerpt`. The model pasted that exact string as its evidence
for two unrelated technical documents. It was rejected only because the string happened not to
appear in those passages — luck, not a mechanism. Had a document contained it, a fabricated card
would have passed the grounding check with the product's own text as proof.

- Example text, placeholders, prompt scaffolding and default values may never satisfy a check
  applied to the output. Name that text in code and refuse it explicitly
  (`EXAMPLE_SOURCE_EXCERPT` in `flashcard_prompts.py`, refused in `flashcard_parsers.py`).
- When a check reads something the model produced, ask where else that value could come from.
  If the answer includes "from us", the check is decorative.

## A check that cannot fail is not a check

**Incident.** The flashcard judge was asked for `atomic` with the term undefined. It returned
`true` for every card in a sample that was two thirds bulleted multi-point answers —
`atomicity 1.0000`. The axis was a rubber stamp, and it would have certified the change that was
supposed to fix it.

- Fire every check before trusting it: make it fail on purpose, once, and see the message.
- Prefer structural checks to judged ones wherever the property is structural. Counting facts in
  an answer needs no model; asking a model whether an answer is atomic invites agreement.
- A rate pinned at `0.0000` or `1.0000` is a bug hypothesis. See `verify-before-reporting.md`.

## Never buy a number by spending the content

**Incident.** A `max_tokens` cap cut the worst-case interactive wait from 173s to 52s and
truncated the stored summary mid-word, dropping half the document's sections. The latency table
looked like a win. The artefact was mutilated.

- Latency, cost and yield may never be improved by silently degrading what the user receives.
- If a bound must exist, bound the work (split the call, assemble from what exists), not the
  output.
- State the product cost of every performance change in the same breath as the gain.

## A fix is validated at the scale the defect appears

**Incident.** A prompt change was validated on a 9-card diagnostic and shipped into a measurement
run, where it nearly doubled rejections and cut delivered cards from 27 to 11. The diagnostic was
the right tool for finding the cause and the wrong tool for confirming the cure.

- Diagnose small, confirm at full scale. The run that found the problem is not the run that
  proves it fixed.
- Two independent runs agreeing is what separates an effect from noise: `0.9259` and `0.9298`
  meant something; `0.7300` against `0.7267` meant nothing.

## Turning a check off is a decision, not a default

**Incident.** `run_model_matrix.py` passes `--skip-judge`, so every model comparison in this repo
reports parse rates and card counts with correctness switched off — the axis a model is actually
chosen for.

- A disabled check must carry the reason it is disabled and what would re-enable it, next to the
  flag.
- Never disable a check to make a run green, a suite pass, or a number quotable.

## Thresholds come from the cases that decide them

A number chosen by intuition will be wrong in the direction nobody tests. The quote-length floor
was four words (which rejected `def factorial(n):`), then fifteen characters (which rejected
`def add(a, b):` at fourteen). It is twelve characters because `def add(a, b):` is checkable and
`"the author"` at ten proves nothing — both cases are written next to the constant.

- Every threshold names the two cases that bracket it, in a comment or a test.
- Loosening a threshold so output passes is the shortcut this whole file exists to forbid. If a
  model cannot meet a rule, report that as a fact about the model.

## Before claiming something is fixed

1. The mechanism is understood, not merely correlated with the symptom disappearing.
2. It ran in the real app, not only in the suite — `make ci` green is necessary, never sufficient.
3. The measurement that would show a regression exists and can move in both directions.
4. What was **not** verified is stated in the same message as what was.
