import manifestJson from "../../../surface-manifest.json"

export type Mode = "full" | "public"

export interface Surface {
  id: string
  mode: Mode
  kind: "nav_tab" | "feature" | "service"
  rail?: "dev"
  frontend?: { route?: string; component?: string; components?: string[] }
  backend?: { routers?: string[]; services?: string[] }
  labels: { en: string }
  description?: string
}

const ORDER: Record<Mode, number> = { public: 0, full: 1 }

// Build-time mode. Set via VITE_LUMINARY_MODE (vite.config defines it from the
// env, defaulting to full for `vite dev` and public for `vite build`).
function resolveMode(): Mode {
  const explicit = import.meta.env.VITE_LUMINARY_MODE as string | undefined
  if (explicit === "full" || explicit === "public") return explicit
  return import.meta.env.DEV ? "full" : "public"
}

export const LUMINARY_MODE: Mode = resolveMode()
export const surfaces = manifestJson.surfaces as unknown as Surface[]

// Mirrors backend `enabled_routers`: a bundle shows every surface at or below
// its mode; there is no per-install toggle.
export function visibleSurfaces(): Surface[] {
  return surfaces.filter((s) => ORDER[s.mode] <= ORDER[LUMINARY_MODE])
}

export function navTabs(): Surface[] {
  return visibleSurfaces().filter((s) => s.kind === "nav_tab")
}

// Is a single surface reachable in this build? Used to gate cross-surface entry
// points (e.g. the "View in graph" doc action) so they disappear when their
// target surface is trimmed from the bundle.
export function isSurfaceVisible(id: string): boolean {
  return visibleSurfaces().some((s) => s.id === id)
}

export function routedSurfaces(): Surface[] {
  return visibleSurfaces().filter((s) => s.frontend?.route)
}
