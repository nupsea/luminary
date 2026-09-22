# Clean up after every major feature

A feature is not done when it works. It is done when the code it left behind is no larger than
the problem needed. Before calling a major feature, a multi-commit fix series or a branch
finished, run a clean-code pass over its own diff (`git diff master...HEAD`) and commit it
separately.

**Comments**

- A comment carries a non-obvious WHY or a load-bearing directive, in one or two lines.
- Cut narration of the investigation, incident retellings, measurements, dated notes and
  "we tried X" — they belong in the commit message or `docs/`.
- Cut comments that restate the next line, and section banners over three-line blocks.
- An invariant reference (`I-56`) replaces the paragraph that explains it.

**Code**

- Delete dead code, unused helpers, parameters and flags the diff made obsolete.
- Fold duplicates: grep for a helper before keeping a second one.
- A function that grew past one screen during the feature gets split or simplified.
- No behaviour change in the cleanup commit. `make ci` green before and after.

The cleanup is scoped to what the feature touched. It is not licence to refactor unrelated code.
