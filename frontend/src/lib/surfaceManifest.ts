import manifestJson from "../../../surface-manifest.json"

export type Tier = "public" | "labs" | "dev"

export interface Surface {
  id: string
  tier: Tier
  kind: "nav_tab" | "feature" | "service"
  frontend?: { route?: string; component?: string; components?: string[] }
  backend?: { routers?: string[]; services?: string[] }
  labels: { en: string }
  description?: string
  default_off?: boolean
}

const ORDER: Record<Tier, number> = { public: 0, labs: 1, dev: 2 }

// Build-time tier. Set via VITE_SURFACE_TIER (vite.config defines it from the
// env, defaulting to dev for `vite dev` and public for `vite build`).
function resolveTier(): Tier {
  const explicit = import.meta.env.VITE_SURFACE_TIER as string | undefined
  if (explicit === "public" || explicit === "labs" || explicit === "dev") return explicit
  return import.meta.env.DEV ? "dev" : "public"
}

export const SURFACE_TIER: Tier = resolveTier()
export const surfaces = manifestJson.surfaces as unknown as Surface[]

// Mirrors backend `enabled_routers`: the dev bundle shows everything compiled in
// and ignores the per-install labs toggle; lower tiers gate labs on the toggle.
export function visibleSurfaces(labsEnabled: Set<string>): Surface[] {
  return surfaces.filter((s) => {
    if (ORDER[s.tier] > ORDER[SURFACE_TIER]) return false
    if (SURFACE_TIER !== "dev" && s.tier === "labs" && !labsEnabled.has(s.id)) return false
    return true
  })
}

export function navTabs(labsEnabled: Set<string>): Surface[] {
  return visibleSurfaces(labsEnabled).filter((s) => s.kind === "nav_tab")
}

// Is a single surface reachable in this build, given the current labs toggles?
// Used to gate cross-surface entry points (e.g. the "View in graph" doc action)
// so they disappear when their target surface is trimmed from the bundle.
export function isSurfaceVisible(id: string, labsEnabled: Set<string>): boolean {
  return visibleSurfaces(labsEnabled).some((s) => s.id === id)
}

export function routedSurfaces(labsEnabled: Set<string>): Surface[] {
  return visibleSurfaces(labsEnabled).filter((s) => s.frontend?.route)
}

// A labs surface that owns a route the user could deep-link into. Used by the
// 404 fallback to tell "gated labs feature" apart from "genuinely unknown URL".
export function findLabsSurfaceByRoute(path: string): Surface | undefined {
  return surfaces.find((s) => s.tier === "labs" && s.frontend?.route === path)
}
