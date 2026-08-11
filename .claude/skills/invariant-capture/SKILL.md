---
name: invariant-capture
description: Turn a debugged incident into a durable invariant in docs/invariants.md, backed by a named test. Use after fixing a bug whose cause was not predictable from reading the code, or when the user says "that should never happen again" / "capture this" / "add an invariant".
---

# Capturing an invariant

`docs/invariants.md` is the highest-value file in this repo because every entry encodes something
no agent could re-derive from the code. Adding to it well is a procedure, not a note.

## Does it qualify?

An invariant is warranted when **the correct behaviour was not predictable from reading the
code**, and a competent engineer would make the same mistake again.

Qualifies:
- The system's behaviour contradicts the obvious assumption. (Kuzu's lock cannot go stale, so
  every "clear the stale lock" fix can only kill a live writer — I-24.)
- A property belongs to a different level than the call site suggests. (`num_ctx` is a property
  of the model, not the call — I-27.)
- Something fails silently rather than loudly. (An unlisted directory in `layer_linter.py`
  resolves to `None` and silently exempts a whole layer.)
- Cost or performance is dominated by an unexpected term. (Enrichment cost is call count, not
  concurrency — I-31.)

Does not qualify: an ordinary bug fix, a style preference, or anything the type checker, `ruff`,
or an existing test already catches. Those are commits, not invariants.

## Procedure

1. **Reduce to a minimal reproduction.** Not the whole failing feature — the smallest thing that
   exhibits the behaviour. If you cannot reproduce it, you do not yet understand it and must not
   write an invariant about it. Treat any 0.00 / 1.00 / whole-leg-dead number as a bug
   hypothesis and reproduce it directly before writing anything down.

2. **Write the failing test first.** It must fail against the pre-fix code for the stated reason.
   A test that passes before the fix guards nothing. Name it for the behaviour, not the bug:
   `test_single_local_context_window.py`, not `test_issue_412.py`.

3. **Confirm the mechanism.** Not "X broke Y" but *why* the system is built such that X must
   break Y. This is the part that transfers to the next situation; without it the rule is
   cargo cult and gets worked around the first time it is inconvenient.

4. **Write the entry** at the end of `docs/invariants.md` under the right heading, taking the
   next `I-<n>`. Four parts, in this order:

   - **Bold one-line rule.** Imperative and absolute. `**I-32. <rule>.**`
   - **The incident**, with measured numbers and what they were measured on. "Measured: a 2ms
     `/tags/graph` took 8.5s sitting behind one all-library traversal."
   - **The mechanism** — why the system makes this inevitable.
   - **The named test**: "`tests/test_x.py` fails CI if …"

5. **Name the test inside the invariant text.** This is the convention that makes this file work.
   It converts prose into a gate: the rule becomes checkable rather than assertable, and a future
   agent can verify compliance instead of claiming it. An invariant with no named enforcer is a
   suggestion — and I-13/I-14 spent months naming a `passes=true` flag and a reviewer that never
   existed, which is worse than no gate at all, because it was unfalsifiable.

6. **Update the count** in `.claude/rules/common/invariants.md` and add a `docs/` cross-reference
   if a longer design doc covers the area.

7. **`make ci`** — the new test has to pass with the fix in place.

## Style

Follow the `project-docs` skill. Specifically here: state what is true now, never narrate the
investigation ("we found", "it turned out", "originally"). Bold the rule, not every clause.
Keep the measured numbers — they are what make the entry persuasive two years from now.

## Superseding one

Revise in place. Do not append a correction beneath stale text and do not leave a superseded
paragraph standing next to its replacement. Keep the number; renumbering breaks every
cross-reference in `docs/` and in the codebase.
