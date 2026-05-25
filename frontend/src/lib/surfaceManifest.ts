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

// Build-time tier. VITE_SURFACE_TIER is the forward switch (Step 3 makes it the
// only one); until then we bridge from the legacy VITE_DEV_SURFACES gate so dev
// and prod keep behaving exactly as before.
function resolveTier(): Tier {
  const explicit = import.meta.env.VITE_SURFACE_TIER as string | undefined
  if (explicit === "public" || explicit === "labs" || explicit === "dev") return explicit
  const legacy = import.meta.env.VITE_DEV_SURFACES as string | undefined
  if (legacy === "true") return "dev"
  if (legacy === "false") return "public"
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

export function routedSurfaces(labsEnabled: Set<string>): Surface[] {
  return visibleSurfaces(labsEnabled).filter((s) => s.frontend?.route)
}

// A labs surface that owns a route the user could deep-link into. Used by the
// 404 fallback to tell "gated labs feature" apart from "genuinely unknown URL".
export function findLabsSurfaceByRoute(path: string): Surface | undefined {
  return surfaces.find((s) => s.tier === "labs" && s.frontend?.route === path)
}
