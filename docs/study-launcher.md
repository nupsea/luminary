---
description: The Study Launcher -- the one sheet every study entry point opens. Scope taxonomy, POST /study/assemble contract, scope resolver. Read before any study-entry or assembly work.
---

# Study Launcher -- one sheet, many doors

The single new piece of UI machinery the [two-lane model](two-lane-model.md) needs. **Every study
entry point in the app opens the same sheet, pre-filled.** It makes "generate from anything" real
without scattering bespoke flows, and it unifies entry points that already exist today.

One tap from any handle gives a good [Study Event](two-lane-model.md#study-events-the-assessment-atom);
the sheet is optional depth for the 20% who want control.

## Scope taxonomy

A scope tells the assembler *how to build the concept/material set*. The 4-phase event logic is
identical regardless of scope -- only the pool differs.

```ts
type Scope =
  | { type: 'daily' }                                  // Lumen's cross-collection pick (Lane A)
  | { type: 'concept';    conceptId: ID }              // a concept node
  | { type: 'collection'; collectionId: ID }
  | { type: 'doc';        documentId: ID }
  | { type: 'note';       noteId: ID }                 // + any linked concepts
  | { type: 'tag';        name: string }
  | { type: 'selection';  documentId: ID; range: [number, number] }
  | { type: 'chat';       sessionId: ID };
```

## Entry points it unifies (most exist today -- route them here)

| Surface | Handle | Opens with scope |
|---|---|---|
| Hub | the daily-call CTA | `daily` |
| Collection page | "Start session" / "Generate questions" | `collection:<id>` |
| Doc overview | "Study this" / "Generate questions" | `doc:<id>` |
| Note (reader/editor) | "Quiz me on this" | `note:<id>` |
| Tag chip / Notes filter | "Quiz me on '<tag>'" | `tag:<name>` |
| Concept node | "Warm this up" / "Generate cards" | `concept:<id>` |
| Reader text selection | "Quiz me on this" | `selection:<range>` |
| Ask thread | "Turn this thread into cards" | `chat:<sessionId>` |

## The sheet (anatomy)

```
+------------------------------------------------------+
| Study                                                |
| Scope    Iceberg collection            [change v]    |
| Mode     (o) Quick quiz  ( ) Full session  ( ) Drill |  <- teach-back option only in full mode
| Length   (o) 5 min  ( ) 15  ( ) 25                   |
| Draw on  [x] due cards (7)  [x] new questions from   |
|            material   [ ] teach-back at the end      |
| Keep     (o) just test me  ( ) save new questions    |
| > Preview: 5 due + 4 generated · mostly Manifests &  |
|            Snapshots · 2 will be unmapped            |
|                                  [Start ->]          |
+------------------------------------------------------+
```

### Behaviour rules

- **Defaults do the right thing.** One tap on Start from any handle = a sensible event.
- **Preview is honest.** Shows due vs generated, mapped vs unmapped, and flags thin scopes
  ("this tag covers 1 short note -- expect ~3 questions").
- **Lane A uses it too.** The Hub call is a pre-filled launcher invocation (`daily`, full session)
  -- proves "one engine."
- **Tier-aware (constitution 11).** The teach-back mode/option renders only when the `feynman`
  surface ships (full mode); otherwise the control is **absent** (not greyed-disabled).
- **Model-down (constitution 9).** If Ollama/LiteLLM is unreachable, "generate" options disable
  with the shipped banner pattern; **"due cards" still starts a pure-FSRS review.**

## Frontend

- New component `frontend/src/components/StudyLauncher.tsx` + a Zustand slice
  `store/launcherStore.ts` holding `{scope, mode, length, sources, keep}`.
- Opened via the existing cross-tab event bus (**I-11**):
  `dispatchEvent(new CustomEvent('luminary:launch-study', { detail: { scope } }))`, handled in
  `App.tsx`. **Do not** use router state or URL hacks.
- Every state has loading/error/empty (**I-10**): empty scope => "Pick something to study."

## Backend

- New endpoint `POST /study/assemble` under the existing `study` router.
  - Request: `{ scope, mode, length, sources, keep }`
  - Response: the assembled item set + preview metadata `{ due_count, generated_count,
    mapped_count, unmapped_count, topic_mix[], thin_scope_warning? }`.
- Assembly in `services/study_assembler.py`: resolve scope -> candidate material -> interleave due
  cards (FSRS) + freshly generated questions -> fit to budget. **Same selection everywhere**:
  prioritize decaying + on the critical path, interleave across sources, fit the time budget.
- Scope resolution in `services/scope_resolver.py`: **one function per scope kind** ->
  concept/material set. `daily` = cross-collection weakest/coldest pick; `concept` = the concept
  plus its weakest neighbours; `collection`/`doc`/`tag` = concepts lit by that scope; `note`/
  `selection`/`chat` = linked concepts + (generation may mint candidate concepts / unmapped cards).

### Invariants to honor

- **I-1** -- no shared `AsyncSession` across `asyncio.gather`.
- **I-2** -- LanceDB calls wrapped in `to_thread` (concept-vector lookups for scope resolution).
- **I-3** -- guard Kuzu `get_next()` with `has_next()` (route/neighbour queries).
- **I-13** -- all generation via LiteLLM. **>=1 pytest** for the new endpoint.

## Done-bar

- Every handle in the table opens the launcher pre-filled; one-tap Start yields a valid event.
- Preview counts match the actual assembled set (incl. mapped/unmapped).
- Teach-back option appears iff `feynman` enabled; absent otherwise.
- Model-down: due-card review still starts; generation gracefully disabled with a banner.
