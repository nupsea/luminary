---
description: How to spend context in this repo. Always loaded.
---

# Context Efficiency

**Read every file you will modify before writing code. Efficiency means reading smartly, not
reading less.** Targeted line ranges, not skipped reads.

- **Schema first.** For a database change start at `models.py`, then the Alembic revision. For
  an API change start at the router's Pydantic schemas and endpoint signatures.
- **Check for a redundant helper before adding one.** Grep for the pattern; this codebase has
  accumulated near-duplicate utilities that way.
- Don't ask about anything already settled in `docs/architecture.md` or `docs/invariants.md`.
- Never open `frontend/src/types/api.ts` (18k generated lines). Grep it for a type name.
