# Product integrity is the product

Luminary's claim is that what it tells you is grounded in what you gave it: an answer cites chunks,
a card quotes a passage, a summary reflects a document, a metric reports a measurement. **A shortcut
that makes output look correct while severing it from its source destroys the only thing this
product sells.** The dangerous defects keep working and keep passing; every rule below is from one
that shipped or nearly did.

## Nothing the system supplies may satisfy a check on its output

A prompt's worked example once supplied the `source_excerpt` a model pasted as evidence; it failed
the grounding check only by luck. Example text, placeholders and defaults are named in code and
refused explicitly (`EXAMPLE_SOURCE_EXCERPT`, refused in `flashcard_parsers.py`). When a check reads
a model's output, ask where else that value could come from; if the answer includes "from us", the
check is decorative.

## A check that cannot fail is not a check

A judge asked for an undefined `atomic` returned `true` for a sample that was two-thirds multi-point
answers. Fire every check once on purpose and read its message. Prefer structural checks to judged
ones wherever the property is structural.

## Saturation and coincidence are bug hypotheses, not findings

Treat as broken until reproduced in isolation: a rate at exactly `0.0000` or `1.0000`; the same value
on two arms that should differ; a pipeline leg reporting nothing; a metric that does not move when
its subject changes. Both of these shipped as findings and were the harness: `first_pass_rate` read
0.0000 on two models because the parser sliced the demanded wrapper away; three summary metrics
matched to four decimals because `/summarize` replayed the stored summary. An anomaly not chased is
reported as an open question, never as a result. A metric with no headroom is not evidence.

## Never buy a number by spending the content

A `max_tokens` cap cut worst-case latency from 173s to 52s and truncated the stored summary
mid-word. Latency, cost and yield may never improve by degrading what the user receives; bound the
work, not the output, and state the product cost of every performance change beside its gain.

## Validate a fix at the scale the defect appears

A prompt fix validated on a 9-card diagnostic halved delivered cards in the real run. Diagnose small,
confirm at full scale; two independent runs agreeing separates an effect from noise.

## Turning a check off is a decision, not a default

A disabled check carries the reason it is off and what would re-enable it, next to the flag. Never
disable one to make a run green, a suite pass or a number quotable.

## Thresholds come from the cases that decide them

Every threshold names the two cases that bracket it, in a comment or a test (the quote floor is 12
characters: `def add(a, b):` is checkable, `"the author"` proves nothing). Loosening a threshold so
output passes is the shortcut this file forbids; if a model cannot meet a rule, report that as a fact
about the model.

## Before calling anything implemented or fixed

1. The mechanism is understood, not merely correlated with the symptom going away.
2. `make ci` green, plus `make smoke` when a wire contract moved. Necessary, never sufficient.
3. The feature ran for real and its output was read, not only the tests' idea of it.
4. Every number is reproduced or traced to the line that produced it, and the measurement that would
   show a regression can move in both directions.
5. What was **not** verified is stated in the same message as what was.
