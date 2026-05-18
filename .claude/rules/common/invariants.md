---
description: Luminary hard invariants. Violations block passes=true.
---
# Luminary Invariants
To save context tokens, the 18 hard invariants (e.g. AsyncSession concurrency, LanceDB sync wrappers, Kuzu get_next() guards, FTS5 shadow queries, 6-layer import rules, UI loading/error states) have been moved to `docs/invariants.md`.

Before finalizing an implementation or conducting a review, you must read `docs/invariants.md` to verify compliance.
