import { create } from "zustand"
import { apiGet, apiPatch } from "@/lib/apiClient"
import { logger } from "@/lib/logger"
import type { Tier } from "@/lib/surfaceManifest"

export interface LabsSurface {
  id: string
  label: string
  description?: string | null
  default_off: boolean
}

interface SurfaceResponse {
  tier: Tier
  labs_enabled: string[]
  available_labs: LabsSurface[]
}

interface SurfaceState {
  tier: Tier | null
  labsEnabled: Set<string>
  availableLabs: LabsSurface[]
  loaded: boolean
  error: string | null
  fetch: () => Promise<void>
  toggle: (id: string, on: boolean) => Promise<void>
}

// Until fetch() resolves we treat the labs set as empty; the nav rail waits on
// `loaded` so there's no flash of disabled surfaces.
export const useSurfaceStore = create<SurfaceState>((set, get) => ({
  tier: null,
  labsEnabled: new Set(),
  availableLabs: [],
  loaded: false,
  error: null,

  fetch: async () => {
    try {
      const data = await apiGet<SurfaceResponse>("/settings/surface")
      set({
        tier: data.tier,
        labsEnabled: new Set(data.labs_enabled),
        availableLabs: data.available_labs,
        loaded: true,
        error: null,
      })
    } catch (e: unknown) {
      logger.warn("[Surface] fetch failed", { error: String(e) })
      // Fail open: render the always-on surfaces rather than blocking the app.
      set({ loaded: true, error: String(e) })
    }
  },

  toggle: async (id, on) => {
    const prev = get().labsEnabled
    const next = new Set(prev)
    if (on) next.add(id)
    else next.delete(id)
    set({ labsEnabled: next })
    try {
      const data = await apiPatch<SurfaceResponse>("/settings/labs", {
        labs_enabled: [...next],
      })
      set({ labsEnabled: new Set(data.labs_enabled) })
    } catch (e: unknown) {
      logger.warn("[Surface] toggle failed", { id, on, error: String(e) })
      set({ labsEnabled: prev })
      throw e
    }
  },
}))
