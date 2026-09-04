---
description: Pointer to the Luminary hard invariants. Always loaded.
---
# Luminary Invariants

The 39 hard invariants live in `docs/invariants.md`. Each is written as incident -> rule ->
mechanism -> the test that guards it, and none of them is derivable from reading the code.

**Read that file before finalizing any backend implementation or conducting a review.** Read it
in full rather than grepping for a keyword: the invariant you are about to violate is rarely the
one you would think to search for.
