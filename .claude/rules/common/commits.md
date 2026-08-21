# Commit messages and changelog entries

Short. A subject line, a few lines of body, stop. This applies equally to
`CHANGELOG.md` entries — a bold lead sentence and, at most, one short sentence
of why. Not the PR-description depth this repo's PR bodies use; that detail
stays in the PR, not the changelog.

Include only:

- **What was wrong**, in one sentence, with the concrete symptom.
- **The rule the fix follows** — not a walkthrough of the diff.
- **The evidence**: the numbers, before and after.
- **What a future reader must not undo**, if anything.

Cut:

- Narration of how the work went, false starts, or what was considered.
- Anything the diff already says.
- Tables, matrices and per-case detail — those belong in `docs/` or the test.
- Context the reader can get from `git log` or the file itself.

The test for every line: **would a maintainer act differently because of it?**
If not, delete it. A long message is not more rigorous; it is harder to read
and it buries the one fact that mattered.
