---
name: frontend-surface
description: Conventions for changing the Luminary React frontend — pages, components, state, data fetching, navigation, tests. Use whenever editing anything under frontend/src, adding a page or nav tab, or wiring a UI surface to a backend route.
---

# Frontend changes

React + TypeScript + Vite, Zustand for state, TanStack Query for fetching, shadcn/ui + Tailwind
for components. Read `frontend/package.json` for versions; do not trust a version stated in
prose anywhere in this repo.

## Never open `frontend/src/types/api.ts`

18,845 generated lines, 565 KB. Opening it destroys the context window. It is generated from the
OpenAPI schema by `make regen-api-types`. Grep it for a specific type name. Never edit it — the
next regeneration overwrites your change.

## Every feature needs three states (I-10)

Loading, error, and empty. No blank panels.

- **Loading** = skeleton in place, not a spinner that blocks the page.
- **Error** = inline message scoped to the section that failed, not a global banner.
- **Empty** = an explicit "No X yet", not an empty div.

A panel that renders nothing while deciding is the single most common UI defect here, and it is
indistinguishable from a crash to the person using it.

## Navigation

- **Cross-tab navigation uses the `luminary:navigate` DOM event plus the Zustand store** (I-11).
  Dispatch `new CustomEvent('luminary:navigate', { detail: { tab, filter } })` and handle it in
  `App.tsx`. Never URL hacks, never React Router state.
- **Contextual back-navigation** — when navigating from a decision point (a Hub card, a document
  action menu, a search result), pass `state: { from: window.location.pathname }`. The
  destination calls `useBackNavigation()`. `setSearchParams` cleanup must pass
  `{ replace: true, state: routeLocation.state }` or `from` is lost. Do **not** pass `from` on
  tab-rail clicks or ⌘+1..6 — those are explicit switches, not decision points.

## Components

- **Never use `MarkdownRenderer` inline in a list or table cell** (I-12). Block elements (`h1`,
  `ul`) inside a `<td>` break layout. Use `stripMarkdown()` from `src/lib/utils.ts` for
  single-line previews.
- Prefer the existing shadcn `Sheet` primitive for side panels and drawers over a one-off.
- Rendering a component from a mapped object needs a capitalized identifier in scope:
  `{(() => { const Icon = MAP[k]; return <Icon /> })()}`. `<MAP[k] />` is not valid JSX.

## Effects and async

- **No "already started" refs in effects.** StrictMode double-invokes effects in development;
  a ref latch that survives the remount makes the second run a no-op in dev and a double-run in
  production. Write effects that are safe to run twice.
- **No `window.open` after an `await`** — the popup blocker kills it once the user gesture has
  been lost. Print via a hidden iframe.
- Use `useQueries()` for N independent per-item fetches, never a mapped `useQuery()` — that
  violates the rules of hooks.
- Gate `setInterval` behind a `useEffect` that depends on the phase, so cleanup halts it
  naturally rather than through manual clearing.

## Tests

**Vitest runs in the `node` environment, not jsdom.** The convention is to extract pure logic
into `lib/` or `store/` helpers and unit-test those. **Do not mount React components in Vitest
tests** — it will not work. `ClozeCard.test.ts` and `focusUtils.test.ts` are the canonical
patterns.

## New page or nav tab

A top-level page under `frontend/src/pages/` must be declared in `surface-manifest.json` with a
`mode`, or `check_manifest_coverage.py` fails `make lint`. `backend/app/surface_manifest.py` and
`frontend/src/lib/surfaceManifest.ts` must stay mirrored — there are no runtime feature toggles,
only `LUMINARY_MODE=full|public` mirrored to the frontend at build time via `VITE_LUMINARY_MODE`.

## When the backend contract changes

Delete the dead consumer code in the same change. After a backend route or field is removed,
grep the frontend for the old endpoint and field names; a stale reference type-checks fine
against a regenerated `api.ts` only until it doesn't.

## Verify

`cd frontend && npx tsc --noEmit && npm run lint`, then `make ci`. For routing changes,
`make verify-router` drives the live UI in a real browser (needs the app running).
