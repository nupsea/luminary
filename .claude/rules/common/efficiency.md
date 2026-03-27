---
description: Context efficiency rules for Claude Code agents. Read before performing any discovery or implementation task.
---

# Context Efficiency Rules

To minimize token usage and maximize response speed, follow these rules.

**Cardinal rule: read every file you will modify before writing code (ralph CLAUDE.md step 7). Efficiency means reading smartly, not reading less.**

## Smart Discovery

- **Use `Grep` to locate patterns**, then `Read` with line ranges for just the relevant section. Avoid reading 1000+ line files in full when you only need a schema or a single function.
- **Use `Glob` to find files by name pattern** (e.g., `**/*flashcard*.py`). Do not use `find` or `ls` via Bash.
- **Parallelize independent searches.** When looking up router + service + models, issue all `Read`/`Grep` calls in a single turn.
- **Always read files you will modify.** The goal is to read surgically (targeted line ranges), not to skip reading entirely.

## Incremental Planning

- When planning a story, use `Grep` to extract the specific story from the PRD rather than reading the entire JSON.
- For large files (500+ lines), read the section you need with offset/limit rather than the whole file.

## Schema-First, Code-Second

- For database changes, start with `models.py` and `db_init.py`. Read the service only if you are modifying it or need to understand its contract.
- For API changes, read the router's Pydantic schemas and endpoint signatures first.

## Redundancy Check

- Before adding a new utility, use `Grep` to search for similar patterns. This avoids codebase bloat.
- Don't ask for clarification on things documented in `architecture.md` or `invariants.md`.

## Output Discipline

- Minimize code in the reasoning part of your response -- let tool calls speak for themselves.
- Do not restate file contents in your response unless the user needs to see them.
