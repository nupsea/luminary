---
description: The Knowledge Universe -- a switchable lens over the concept graph, not a replacement home. Tiered render layers, graceful degrade. Read before any Universe/Map/graph-viz work.
---

# Knowledge Universe -- a lens, not a home

The Knowledge Universe is the product's emotional wow: knowledge as a night sky, warmth = mastery x
recency, dashed rings = gaps, an amber route = the plan. Two facts from the shipped product
constrain it:

1. **The Hub is the shipped home and works** (activity-driven daily call).
2. **Cross-library concept linking is a labs feature** (`concept_linker`).

So (Decision D1, locked) the Universe ships as a **switchable lens** -- you switch the Map (and
optionally the Hub) into it -- degrading gracefully. It is **not** a new graph engine: it is a
themed render mode + warmth shader over the existing **Sigma.js / Graphology** Map.

> Universe = the [concept](concepts.md) graph, **global** (all collections) and emotionally framed.
> Library Map = the same graph, **scoped** to a collection + analytically framed. Same data, two
> framings. The Universe is never a separate content bucket and never a nav-replacing home.

## Tiered render layers (constitution 11; invariant I-10)

| Layer | Source | When |
|---|---|---|
| Documents · concepts (the baseline sky) | `graph` router (public) | **always** |
| Warmth (mastery x recency) | `mastery` + FSRS | **always** |
| Concept<->concept edges (the dense web) | `concept_linker` | only when enabled; else concepts render as independent stars |
| Gaps (route concepts with no covering doc) | `goals` + graph | only when a Plan/goal exists |
| The route (amber path) | `goals` | only with an active plan |

**Graceful degrade:** with `concept_linker` OFF the Universe is still a meaningful field of
warm/cool stars grouped by document/collection -- **never** a blank or broken graph. With no active
plan, simply no route/gaps -- the sky still renders.

## Visual encoding

- **Star** = a concept. Warm/bright = strong + fresh; fading grey = decaying (low warmth).
- **Dimmer star** = a `candidate` concept (origin note/quiz/chat/import, not yet grounded).
- **Lighter star** = `proposed`; solid = `confirmed`.
- **Dashed ring** = a gap on a goal's route.
- **Amber path** = the active plan's route.
- **Soft tinted hull** = a collection (zoom out); expands into its concept stars (zoom in). A
  collection is never a leaf you study -- it is a collapsed cluster.

## Interaction (orientation -> action -- constitution 10)

- **Attention rail** -- <=3 named things to do (coldest-but-important · gate-blocking ·
  misconception). Each routes somewhere.
- **Star panel** -- concept detail: evidence quotes (the [trust receipt](concepts.md#representation----two-truths-two-derived-projections)),
  mastery/recency, "N notes touch this", source docs, and **Study / Generate** ->
  the [Study Launcher](study-launcher.md) with `concept:<id>`.
- Every element routes somewhere; nothing is admire-only. The canvas itself is **read-only** (a
  lens) -- corrections happen on the Map's edit affordances (drag-to-merge, right-click reject,
  drag-between to propose an edge).

## Build notes

- Reuse the existing Sigma.js/Graphology foundation in the `Viz`/`Map` page; add a themed render
  mode + a warmth shader. Do **not** introduce a new graph library.
- Theme-aware (already built in the v4 kit): deep-space dark, dawn-atlas light.
- Switchable from the Map (and Hub if D1 ever flips) **without a full reload**.
- Concept warmth re-renders after a Study Event writes back -- the star visibly re-warms on both
  the Universe and the scoped Library Map.

## Done-bar

- Renders meaningfully with `concept_linker` OFF (baseline) and richer when ON.
- Star panel opens the Launcher correctly scoped.
- Switchable from Map without a full reload.
- Completing a session re-warms the practiced concepts' stars.
