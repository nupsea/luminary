# Verify before reporting

A number is a claim, and reporting it spends it. Verify the instrument before the subject: run
the thing, read its real output, and reproduce anything surprising directly. A green suite says
the code does what the test says — never that the measurement means anything.

**Saturation and coincidence are bug hypotheses, not findings.** Treat as broken until reproduced
in isolation:

- a rate at exactly `0.0000` or `1.0000`
- the same value on two arms that should differ — above all to full float precision
- a whole leg of a pipeline reporting nothing, or every row scoring alike
- a metric that does not move when the thing it measures changes

Both of these shipped as "findings" in one session before being checked, and both were the
harness. `first_pass_rate` read 0.0000 on a 3B model *and* a 14B one: `_parse_llm_response` tried
the array parser first, so `{"flashcards": […]}` — the shape the prompt demands — was sliced to
its inner array and its own wrapper counted as prose around it. Three summary metrics matched to
four decimals across two models: `POST /summarize/{id}` replays the stored summary unless asked to
refresh, so neither model had generated anything.

The tell in both cases was visible in the first table. An anomaly noticed and not chased belongs
in the report as an open question, never as a result.

**Before calling anything implemented:**

1. `make ci` green, plus `make smoke` when a wire contract moved.
2. The feature run for real, its output read — not the tests' idea of it.
3. Every number reproduced, or traced to the line that produced it.
4. What was **not** measured stated in the same breath as what was.

A metric with no headroom is not evidence. If a number cannot move in either direction, say so
instead of quoting it, and fix the instrument before spending anything on it.
