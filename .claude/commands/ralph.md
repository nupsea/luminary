---
name: ralph
description: Add a new story to prd-v3.json in the correct Luminary format. Use when you have a feature idea or requirement and want to queue it for ralph to implement. Triggers on: add story, new story, queue this for ralph, add to prd.
user-invocable: true
---

# Add Story to Luminary PRD

Converts a feature description into a properly-formatted story in `scripts/ralph/prd-v3.json`.

## Story Size Rule

**Each story must be completable in one ralph iteration (one context window).**

Each ralph iteration is a fresh Claude instance with no memory of prior work. If a story is too large, the agent runs out of context mid-implementation.

**Right-sized stories:**
- Add a new SQLAlchemy model + migration + CRUD service + router + tests
- Add a UI component to an existing page
- Add a new chart or panel to an existing tab
- Add one new API endpoint with business logic

**Too large -- split:**
- "Build the entire Notes tab" -- split by: schema, service, router, UI tree, drag-drop, tests
- "Add authentication" -- split by: schema, middleware, login UI, session handling
- "Refactor the retriever" -- split per retrieval strategy or query type

Rule of thumb: if you cannot describe the full implementation in 3 sentences, split it.

## Priority Assignment

Stories execute in priority order (lowest number first). Before assigning a priority:
1. Read the current stories in `scripts/ralph/prd-v3.json` to see what is pending
2. Check dependencies: does this story require a prior story to be implemented first?
3. Assign priority = (highest pending priority + 1) unless it must run before something pending

## Required Fields

```json
{
  "id": "S<next>",
  "title": "<verb phrase, max 10 words>",
  "phase": "V3 Phase 1 - Note Organization and Knowledge Graph",
  "priority": <integer>,
  "featureRef": "F-<DOMAIN>-V3",
  "passes": false,
  "description": "CONTEXT: <current state that makes this necessary>\n\nUSER JOURNEY: <User does X in [Tab] -> sees Y>\n\nCROSS-STORY IMPACT: <prior story IDs affected, or None>\n\nIMPLEMENTATION NOTES: <key constraints, files to touch>",
  "acceptanceCriteria": [
    "<verifiable criterion>",
    "...",
    "npx tsc --noEmit exits 0; uv run ruff check . exits 0; uv run pytest exits 0",
    "scripts/smoke/S<n>.sh exits 0"
  ]
}
```

## Acceptance Criteria Rules

Every AC must be **verifiable** -- something claude can confirm by running a command or reading output.

**Good:**
- "GET /collections/tree returns nested JSON with note_count on each node"
- "Dragging a note row onto a CollectionTree item fires POST /notes/{id}/collections"
- "TagTree renders with correct parent/child nesting and counts"

**Bad:**
- "Works correctly"
- "User can organize notes"
- "Good performance"

Always include as the final two criteria:
```
"npx tsc --noEmit exits 0; uv run ruff check . exits 0; uv run pytest exits 0",
"scripts/smoke/S<n>.sh exits 0"
```

For stories with UI changes, also include:
```
"<ComponentName> renders correctly: loading skeleton, error state with message, empty state with message"
```

## What to Do

1. Read `scripts/ralph/prd-v3.json` -- find the next story ID (last id + 1) and the highest current priority
2. Ask the user any critical clarifying questions (max 3, with lettered options) if the description is ambiguous
3. Draft the story JSON following the format above
4. Show the draft to the user for confirmation
5. On confirmation, append it to the `stories` array in `scripts/ralph/prd-v3.json`
6. Report: "Added S<n> (P<priority>) to prd-v3.json"
