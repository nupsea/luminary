Closes #

## What and why

<!-- Two or three lines: what was wrong or missing, and the rule the change follows. The diff says the rest. -->

## How it was checked

<!-- What you ran and what you looked at. Paste the tail of `make ci`. For a UI change, a screenshot or recording. -->

**Not checked:** <!-- what you could not verify, e.g. a platform you do not have -->

## AI use

- Tools: <!-- e.g. none, Claude Code, Cursor, Copilot -->
- How much: <!-- none / suggestions / most of the diff -->

## Checklist

- [ ] The linked issue carries the `accepted` label
- [ ] I have read every line of this diff and can explain it
- [ ] `make ci` passes locally
- [ ] `make smoke` passes, if an endpoint's request or response changed
- [ ] Every commit is signed off (`git commit -s`)
- [ ] A schema change came from `make db-revision`, and I read the revision for unintended drops
- [ ] A new or bumped dependency is named here with its licence, and `make ci`'s licence check passes
