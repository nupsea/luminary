---
name: project-docs
description: Standards for writing and editing anything in docs/, README.md, CHANGELOG.md, or a module docstring in this repo. Use whenever adding or revising project documentation, or when a chat answer is about to be written down.
---

# Writing documentation for Luminary

Documentation exists so a maintainer can act correctly without re-deriving what
was already worked out. It is not a transcript of how the answer was reached.

## The test

For every sentence: **would a maintainer do something different because of it?**
If not, delete it.

## Record

- The decision, and the constraint that forces it.
- The failure mode if it is violated — especially silent ones.
- Where it is enforced (test, CI gate, script).
- Measured numbers, with what they were measured on.
- Facts that contradict the obvious assumption. These are the highest-value
  lines in any doc, because they are what someone will otherwise get wrong.

## Cut

- **Answers to questions nobody will ask again.** A chat question deserves a
  chat answer. It only becomes documentation if a maintainer would hit the same
  fork.
- **Rebuttals of options that were never adopted.** "X does not help because..."
  belongs in a doc only when someone is likely to propose X again — then it is
  one line: the option and the disqualifying fact.
- **Rhetorical framing.** "Two reasons, and the second is the binding one."
  "It is worth noting that." Say the thing.
- **Narration of the work.** "We investigated", "it turned out", "originally".
  State what is true now.
- **Emphasis inflation.** Bold on every clause reads as none. Bold the term
  being defined, not the sentence.
- **Changelog in reference docs.** Git history covers what changed; reference
  docs describe what is.

## Shape

- Lead with what the reader needs to do or avoid.
- Enumerable facts go in a table or list, not prose.
- One topic per heading; if a section needs "also", it is two sections.
- Link to code rather than restating it — code drifts, prose drifts faster.

## When editing

Revise in place. Do not append a correction under the stale text, and do not
leave a superseded paragraph standing next to its replacement. If a fact
changed, the old sentence goes.

Check that referenced symbols, flags and paths still exist before leaving them
in — a doc naming a function that was renamed is worse than no doc.
