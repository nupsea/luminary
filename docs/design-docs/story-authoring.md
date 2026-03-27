# Story Authoring Guide

This document defines how to write stories in `prd-v2.json` that ralph can implement
correctly and that will actually work for the user end-to-end.

The patterns here were extracted from post-mortems on stories that passed all ACs
but shipped broken user experiences.

---

## Why Stories Fail Despite Passing Tests

Three root causes recur:

1. **Isolated ACs** -- each story tested its own API slice but no story owned the seam
   between two features crossing tabs or components.
2. **Phantom data paths** -- a code path compiled and unit-tested fine, but the data
   it needed only existed if the user had performed an optional prior step.
3. **Classifier not tested against real UI inputs** -- a heuristic worked on synthetic
   test strings but not the exact suggested prompts shown in the UI.

---

## Required Elements for Every Story

### 1. User Journey Statement

Every story description must include a one-sentence user journey in the form:

> "User does X in [Tab/Component] -> [what happens] -> User sees Y."

This is not optional prose -- it is the spec that ACs must cover.

**Bad (no journey):**
> "This story adds GET /notes/gaps and a GapResultCard component."

**Good:**
> "User is in Notes tab, clicks 'Compare with Book', selects a document, and sees
> a gap analysis card showing concepts from the book absent from their notes."

---

### 2. End-to-End Flow AC

Any story that introduces or modifies a user-facing feature must include at least one
AC that tests the complete path from UI action to visible output, not just the API.

Pattern:

> "User flow: [action in UI A] -> [navigates to / updates UI B] -> [visible result]
> works end-to-end without error."

The smoke test for the story (`scripts/smoke/SXXX.sh`) must exercise this path over
real HTTP, not just curl the new endpoint in isolation.

---

### 3. Cross-Story Impact Section

When a story modifies a feature introduced in a prior story, the description must
explicitly list the prior story IDs and state which of their ACs are affected.

Pattern in description:

> "CROSS-STORY IMPACT: S94 added GapDetectDialog and a 'Compare with Book' button
> in Notes.tsx that navigated to /chat. S96 moved gap detection into the chat stream,
> which broke that navigation. This story must fix the Notes button to open the dialog
> directly."

This section is the contract that prevents regression by omission.

---

### 4. Classifier/Filter AC Against UI Surface Inputs (core-belief #23)

Any story that introduces or modifies a classifier, intent router, keyword filter, or
stopword list must include an AC that tests against the exact strings visible in the UI
(example questions, suggestion pills, autocomplete options).

Pattern:

> "Parametrized test covers all strings in Chat.tsx EXAMPLE_QUESTIONS and
> getContextualSuggestions() -- none must produce a false positive in [classifier]."

Implementation rule: when you add a UI suggestion string, add it to the classifier's
parametrized test in the same commit.

---

### 5. Three Frontend States (invariant #13 reminder)

Every frontend story AC must include one criterion each for:
- Loading state (skeleton, not spinner blocking the page)
- Error state (inline message per section, not blank)
- Empty state (explicit message, not blank)

---

## Smoke Test Quality Standard

`scripts/smoke/SXXX.sh` must do more than curl one endpoint.

**Minimum for a single-feature story:**
```bash
# 1. Set up: POST seed data if needed
# 2. Exercise the feature: call the endpoint being introduced
# 3. Assert the response: check HTTP status AND non-empty / structurally valid body
# 4. Exercise the UI entry point: if a button/pill triggers the feature,
#    simulate the equivalent API call that the UI would make
```

**For cross-tab flows:**
```bash
# Simulate the full sequence of API calls the user journey would make:
# e.g. GET /notes -> confirm notes exist -> POST /notes/gaps -> assert gap card
```

Smoke tests cannot verify rendered UI. They verify the backend contract that the UI
depends on. A smoke test that only curls the new endpoint is insufficient when the
story involves a user flow spanning multiple API calls.

---

## Story Description Template

```
CONTEXT: [1-2 sentences on the current state that makes this story necessary]

USER JOURNEY: [one sentence: User does X in [Tab] -> sees Y]

CROSS-STORY IMPACT: [list prior story IDs and which ACs are affected, or "None"]

IMPLEMENTATION NOTES: [optional -- known constraints, existing code to modify]
```

---

## Common Anti-Patterns to Reject

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| ACs are only unit tests + tsc/ruff | Passes CI but ships broken UX | Add end-to-end flow AC |
| Navigation to `/chat?q=...` from another tab | Scope/context lost in navigation | Open dialog or pass document_id in URL params |
| Stopword list tested only on synthetic strings | UI suggestion words slip through | Test against EXAMPLE_QUESTIONS and pill labels |
| `passes=true` without smoke test verification | Feature works in unit tests, 404s in browser | Smoke test required before passes=true |
| Cross-tab state assumed to persist across navigation | React state resets on route change | Use URL params or Zustand store for cross-tab state |

---

## Checklist Before Setting passes=true

- [ ] User journey statement is in the description
- [ ] At least one end-to-end flow AC exists and is satisfied
- [ ] Cross-story impact section lists all affected prior stories
- [ ] If a classifier/filter was modified: parametrized test covers UI surface inputs
- [ ] Three frontend states are covered in ACs (loading, error, empty)
- [ ] Smoke test exercises the full user journey sequence, not just the new endpoint
- [ ] `luminary-reviewer` returned no Critical items
- [ ] `ruff check`, `pytest`, `tsc --noEmit` all pass
