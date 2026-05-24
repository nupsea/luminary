# Labs drawer — engineering spec (Phase 3, Track 1)

Status: spec, not yet implemented
Drafted: 2026-05-23
Owner doc: `docs/phase-3-plan.md` (Track 1)

> The mechanism that lets one repo ship as one public product while keeping the polymath features (labs) and engineering surfaces (dev) inside the same codebase. Without this, "public bundle" is wishful thinking.

---

## Design decisions (locked)

1. **Two gating mechanisms, not one.**
   - `dev` tier → **build-time strip**. Public/labs bundles do not compile dev code. There is no runtime path from a public bundle to Phoenix, Quality dashboards, RAGAS runner, or admin endpoints.
   - `labs` tier → **runtime toggle**. Labs code ships in public bundles. Default state: hidden. User reveals via Settings → Labs. Re-enabling a labs feature does not require a rebuild.

2. **One manifest, hand-edited JSON, at repo root.** Path: `surface-manifest.json`. Both backend (Python) and frontend (TypeScript) parse the same file. No codegen, no duplication, no YAML. A CI lint enforces that every router and every top-level route either appears in the manifest or is on the public allow-list.

3. **Tier is set at build time via `LUMINARY_SURFACE_TIER`.** Values: `public | labs | dev`. Public production bundles use `public`. Author's daily dev uses `dev`. `labs` is for QA/preview builds. The runtime user toggle is layered *on top of* a `public` or `labs` tier — it can only reveal features within the tier the bundle was compiled with.

4. **Labs toggle persistence is per-install, not per-tab.** Stored in the existing `user_settings` SQLite table. Single JSON column: `labs_enabled: ["feynman", "youtube_ingest", ...]`. Frontend reads at boot, mutates via `PATCH /settings/labs`.

5. **No filesystem reorganization.** Services and components stay where they are. The manifest is the only source of truth for tier. Files do not move into `services/labs/` or `components/labs/`. Movement would churn imports for zero benefit; the manifest plus a CI lint catches drift just as well.

---

## The manifest

### File: `surface-manifest.json` (repo root)

```json
{
  "version": 1,
  "surfaces": [
    {
      "id": "library",
      "tier": "public",
      "kind": "nav_tab",
      "frontend": { "route": "/library", "component": "pages/Learning" },
      "backend": { "routers": ["documents", "sections", "reading"] },
      "labels": { "en": "Library" }
    },
    {
      "id": "feynman",
      "tier": "labs",
      "kind": "feature",
      "frontend": { "components": ["components/Teachback", "components/TeachbackSession"] },
      "backend": { "routers": ["feynman"], "services": ["feynman_service", "feynman_strategies"] },
      "labels": { "en": "Feynman / Teach-back" },
      "description": "Socratic explanation sessions graded against source material.",
      "default_off": true
    },
    {
      "id": "quality_dashboard",
      "tier": "dev",
      "kind": "nav_tab",
      "frontend": { "route": "/quality", "component": "pages/Quality" },
      "backend": { "routers": ["evals"] },
      "labels": { "en": "Quality" }
    }
  ]
}
```

### Schema

| Field | Type | Notes |
|---|---|---|
| `version` | int | Bumped on breaking schema changes. Manifest reader rejects unknown versions. |
| `surfaces[].id` | string | Stable identifier. Used as the key for user labs toggles. Snake_case. |
| `surfaces[].tier` | `"public" \| "labs" \| "dev"` | Lower bound: a `dev` surface is invisible in `labs` and `public` builds. |
| `surfaces[].kind` | `"nav_tab" \| "feature" \| "service"` | `nav_tab` shows in the sidebar; `feature` is a UI-only surface (a panel, a dialog); `service` is backend-only (e.g. a background enrichment worker). |
| `surfaces[].frontend.route` | string? | If present, registered with React Router on tiers >= the surface's tier. |
| `surfaces[].frontend.component` | string? | Lazy-load path relative to `frontend/src/`. |
| `surfaces[].frontend.components[]` | string[]? | For features that don't own a route — components that should not be rendered when the feature is gated off. |
| `surfaces[].backend.routers[]` | string[]? | Module names under `backend/app/routers/`. Registered only when tier permits and (for labs) the user has not disabled the feature server-side. |
| `surfaces[].backend.services[]` | string[]? | Informational — for the CI lint to verify coverage. |
| `surfaces[].labels.en` | string | UI label. Localization deferred. |
| `surfaces[].description` | string? | Shown in Settings → Labs. Required for `labs` tier. |
| `surfaces[].default_off` | bool? | Labs only. If true, the feature is hidden by default even on `labs` builds. |

### Tier semantics

| Bundle tier | What's compiled in | What's visible at runtime |
|---|---|---|
| `public` | `public` only | `public` always; `labs` only when user has enabled in Settings |
| `labs` | `public` + `labs` | `public` always; `labs` per user setting (defaults: all labs on except `default_off: true`) |
| `dev` | `public` + `labs` + `dev` | Everything. No gating. |

---

## Backend implementation

### File: `backend/app/surface_manifest.py` (new)

Pure loader + queries. No I/O at import time — read on first use.

```python
from functools import lru_cache
from pathlib import Path
import json

@lru_cache(maxsize=1)
def _manifest() -> dict:
    path = Path(__file__).resolve().parents[2] / "surface-manifest.json"
    with path.open() as f:
        data = json.load(f)
    if data.get("version") != 1:
        raise RuntimeError(f"unsupported manifest version: {data.get('version')}")
    return data

def surfaces_for_tier(tier: str) -> list[dict]:
    order = {"public": 0, "labs": 1, "dev": 2}
    bundle_rank = order[tier]
    return [s for s in _manifest()["surfaces"] if order[s["tier"]] <= bundle_rank]

def enabled_routers(tier: str, labs_enabled: set[str]) -> set[str]:
    out: set[str] = set()
    for s in surfaces_for_tier(tier):
        if s["tier"] == "labs" and s["id"] not in labs_enabled:
            continue
        for r in (s.get("backend") or {}).get("routers", []):
            out.add(r)
    return out
```

### File: `backend/app/config.py` (modify)

Add one setting:

```python
LUMINARY_SURFACE_TIER: Literal["public", "labs", "dev"] = "dev"
```

Default `dev` so existing dev workflows don't break. Production bundles set `LUMINARY_SURFACE_TIER=public` in their env or Dockerfile.

### File: `backend/app/main.py` (modify)

Router registration consults the manifest. Today, `main.py` imports every router and registers it unconditionally. New flow:

```python
from app.surface_manifest import enabled_routers
from app.services.settings_service import get_labs_enabled

async def lifespan(app):
    tier = settings.LUMINARY_SURFACE_TIER
    labs = await get_labs_enabled() if tier != "dev" else set()
    for router_name in enabled_routers(tier, labs):
        module = importlib.import_module(f"app.routers.{router_name}")
        app.include_router(module.router)
    yield
```

Two caveats:

1. **Routers can no longer be registered at module import time.** Today some routers may be wired via decorator side effects. Switch all of them to `router = APIRouter(...)` + explicit `app.include_router()` in the lifespan. CI lint enforces this.
2. **Toggling labs at runtime requires a backend restart.** Acceptable trade-off — labs toggles are rare. If we want hot toggling later, swap to a middleware that 404s requests against disabled routers. Defer.

### File: `backend/app/services/settings_service.py` (modify)

Add two functions:

```python
async def get_labs_enabled() -> set[str]:
    ...  # read user_settings JSON, default to {} on first run

async def set_labs_enabled(features: set[str]) -> None:
    ...  # validate each id exists in manifest with tier=labs; persist
```

### File: `backend/app/routers/settings.py` (modify)

Two new endpoints:

- `GET /settings/surface` → `{ tier, labs_enabled: [...], available_labs: [...] }` where `available_labs` is the manifest-derived list of labs surfaces (id, label, description, default_off).
- `PATCH /settings/labs` → body `{ labs_enabled: [...] }`. Validates against manifest. Returns 400 on unknown id or non-labs tier.

### Schema migration

Add to `user_settings`:

```sql
ALTER TABLE user_settings ADD COLUMN labs_enabled TEXT NOT NULL DEFAULT '[]';
```

Stored as JSON array of surface ids. No new table.

---

## Frontend implementation

### Build-time strip (`dev` tier)

This is the only place the build tooling has real work to do.

#### File: `frontend/vite.config.ts` (modify)

```ts
import surfaceManifest from "../surface-manifest.json";

const tier = process.env.VITE_SURFACE_TIER ?? "dev";
const tierOrder = { public: 0, labs: 1, dev: 2 };
const allowedTier = tierOrder[tier];

const strippedAliases: Record<string, string> = {};
for (const surface of surfaceManifest.surfaces) {
  if (tierOrder[surface.tier] > allowedTier) {
    const comp = surface.frontend?.component;
    if (comp) strippedAliases[`@/${comp}`] = "@/lib/strippedSurface";
    for (const c of surface.frontend?.components ?? []) {
      strippedAliases[`@/${c}`] = "@/lib/strippedSurface";
    }
  }
}

export default defineConfig({
  resolve: { alias: strippedAliases },
  define: { __SURFACE_TIER__: JSON.stringify(tier) },
  // ...
});
```

#### File: `frontend/src/lib/strippedSurface.tsx` (new)

```tsx
export default function StrippedSurface() {
  return null;
}
```

Imports of stripped components resolve to a no-op component. Routes pointing at them render nothing; nav rail filters them out before rendering anyway, so this is defense in depth.

### Manifest consumer

#### File: `frontend/src/lib/surfaceManifest.ts` (new)

```ts
import manifestJson from "../../../surface-manifest.json";

export type Tier = "public" | "labs" | "dev";

export interface Surface {
  id: string;
  tier: Tier;
  kind: "nav_tab" | "feature" | "service";
  frontend?: { route?: string; component?: string; components?: string[] };
  labels: { en: string };
  description?: string;
  default_off?: boolean;
}

export const SURFACE_TIER = (import.meta as any).env.VITE_SURFACE_TIER as Tier;
export const surfaces = manifestJson.surfaces as Surface[];

const order: Record<Tier, number> = { public: 0, labs: 1, dev: 2 };

export function visibleSurfaces(labsEnabled: Set<string>): Surface[] {
  return surfaces.filter(s => {
    if (order[s.tier] > order[SURFACE_TIER]) return false;
    if (s.tier === "labs" && !labsEnabled.has(s.id)) return false;
    return true;
  });
}

export function navTabs(labsEnabled: Set<string>): Surface[] {
  return visibleSurfaces(labsEnabled).filter(s => s.kind === "nav_tab");
}
```

### Settings store + boot fetch

#### File: `frontend/src/store/surfaceStore.ts` (new)

Zustand slice:

```ts
interface SurfaceState {
  labsEnabled: Set<string>;
  loaded: boolean;
  setLabsEnabled: (next: Set<string>) => void;
  fetch: () => Promise<void>;
  toggle: (id: string, on: boolean) => Promise<void>;
}
```

`fetch()` hits `GET /settings/surface` on app boot (called from `App.tsx`). Until `loaded` is true, nav rail renders a skeleton — no flash of disabled surfaces.

### Route registration

#### File: `frontend/src/App.tsx` (modify)

Replaces today's hard-coded `<Route path="..." element={...} />` block with a manifest-driven map:

```tsx
const { labsEnabled, loaded } = useSurfaceStore();
const tabs = useMemo(() => navTabs(labsEnabled), [labsEnabled]);

if (!loaded) return <BootSkeleton />;

return (
  <Routes>
    {tabs.map(s => (
      <Route
        key={s.id}
        path={s.frontend!.route!}
        element={<Suspense fallback={<RouteSkeleton />}>{lazyLoad(s.frontend!.component!)}</Suspense>}
      />
    ))}
    <Route path="*" element={<NotFoundRedirect />} />
  </Routes>
);
```

`NotFoundRedirect` is the key UX moment: if the user lands on `/feynman` but the feature is gated off, redirect to `/settings?focus=labs.feynman` with a toast: "Feynman is a Labs feature — enable it below." This makes deep links into labs surfaces self-healing.

### Nav rail

#### File: `frontend/src/components/Sidebar.tsx` (modify, or wherever the rail lives)

The rail's `tabs` array becomes `navTabs(labsEnabled)`. Icons are looked up by `surface.id` from a separate icon registry. Labels come from `surface.labels.en`.

### Settings → Labs panel

#### File: `frontend/src/components/SettingsDrawer.tsx` (modify) + `frontend/src/components/SettingsLabsPanel.tsx` (new)

New section in the existing settings drawer. Visible only on `labs` and `dev` builds. Lists each labs-tier surface from the manifest with:

- Toggle (on/off)
- Label + description
- "Experimental — may change or be removed" caveat at the top of the section
- "Restart not required" hint (true for UI features; labs surfaces backed by `backend.routers` get an info pill "Backend restart required to use these endpoints")

Toggle calls `surfaceStore.toggle(id, on)` which `PATCH`es and updates local state optimistically.

### Cross-tab event bus

The existing `luminary:navigate` event (from `App.tsx`, used by Study links, note source links, ⌘K results, etc.) currently dispatches to any route string. New constraint: before dispatching, the emitter or the listener must check `visibleSurfaces(labsEnabled).find(s => s.frontend?.route === target)`. If absent, fall through to `NotFoundRedirect`. Simplest place to enforce: the listener in `App.tsx`. Emitters stay unchanged.

---

## CI enforcement

### Lint 1: manifest coverage

#### File: `scripts/check_manifest_coverage.py` (new)

Walks `backend/app/routers/*.py` and `frontend/src/pages/*` and asserts each is either:

- referenced in `surface-manifest.json`, or
- listed in an explicit allow-list at the top of the script (for cross-cutting routers like `settings`, `home`, `chat_sessions`).

Fails CI on uncovered files. Forces every new router/page to declare its tier.

Wired into `make lint`.

### Lint 2: schema validity

#### File: `scripts/check_manifest_schema.py` (new)

Validates:

- All `tier` values are `public | labs | dev`.
- All `kind` values are `nav_tab | feature | service`.
- `nav_tab` surfaces must have `frontend.route` and `frontend.component`.
- `labs`-tier surfaces must have `description`.
- No duplicate `id`s.
- No duplicate `frontend.route`s.
- Every referenced backend router exists in `backend/app/routers/`.
- Every referenced frontend component path exists under `frontend/src/`.

Wired into `make lint`.

### Lint 3: import discipline

A `dev`-tier file (Quality dashboard, etc.) must not be imported from `public` or `labs` code. The existing layer linter pattern extends to this: parse imports, reject anything that violates the tier hierarchy.

---

## Migration from `VITE_DEV_SURFACES` (Phase 2F.5)

`VITE_DEV_SURFACES` is the current binary gate. Migration is mechanical:

1. Anywhere in the codebase that branches on `import.meta.env.VITE_DEV_SURFACES`, replace with a tier check (`SURFACE_TIER === "dev"`).
2. Delete the env var from `vite.config.ts`, `.env.example`, and `Makefile`. Replace with `VITE_SURFACE_TIER`.
3. Update `App.tsx:437-442` (the dev-route block) to be generated from the manifest instead of conditionally rendered.

After migration, `VITE_DEV_SURFACES` is gone. Single mechanism going forward.

---

## Initial manifest content (Phase 3 starting state)

Based on the surface inventory in `phase-3-plan.md`:

### `public`

`library` · `notes` · `study` · `ask` · `map` · `progress` · `luminary_hub` · `settings` (always-on, not gated) · `collections` · `tags` · `home_overview`

Backend routers: `documents`, `notes`, `flashcards`, `study`, `qa`, `chat_sessions`, `chat_meta`, `summarize`, `search`, `sections`, `collections`, `tags`, `home`, `engagement`, `mastery`, `goals`, `settings`, `annotations`, `reading`, `references`, `graph`, `clips`.

### `labs`

`feynman` · `youtube_ingest` · `audio_transcribe` · `code_parsing` · `web_search` · `code_executor` · `image_enrichment` · `concept_linker` · `clustering_orgplan` · `dataset_generator` · `pomodoro` (re-evaluate after first-5-minutes audit)

Backend routers: `feynman`, `code_executor`, `images`, `explain` (verify).

### `dev`

`quality_dashboard` · `admin` · `evals_dashboard` · `monitoring`

Backend routers: `evals`, `admin`, `monitoring`.

---

## Out of scope for this track

- **Per-user labs settings synced across devices.** Single-user local app; per-install is fine.
- **Hot-reload of backend tier without restart.** Deferred; restart is acceptable for the cadence at which tier changes.
- **Localized labs descriptions.** English-only for v1.
- **Featured / recently-added labs surfacing.** Settings → Labs is a flat list for v1.
- **A/B testing infrastructure on labs.** This is a release mechanism, not an experimentation framework.

---

## Done bar for Track 1

- `surface-manifest.json` exists at repo root with the initial inventory above.
- `VITE_SURFACE_TIER=public npm run build` produces a bundle that does not contain Phoenix/Quality/Admin code (verified by bundle-size diff and a grep on the dist).
- Booting that bundle shows only the six learner tabs + settings. No `/quality`, no `/admin`, no Phoenix link.
- Enabling Feynman in Settings → Labs makes the Teachback components reachable from Study. Disabling hides them again. No rebuild required.
- A user landing on `/feynman` via a stale bookmark while Feynman is disabled is redirected to Settings with a clear message, not a 404.
- CI lints fail when a new router is added without a manifest entry.
- The `LUMINARY_SURFACE_TIER` env var is the single switch; `VITE_DEV_SURFACES` no longer exists.
