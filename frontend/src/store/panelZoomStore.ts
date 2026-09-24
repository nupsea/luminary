import { create } from "zustand"
import { persist, createJSONStorage } from "zustand/middleware"

export const MIN_PANEL_ZOOM = 0.7
export const MAX_PANEL_ZOOM = 2.0
export const PANEL_ZOOM_STEP = 0.1
export const DEFAULT_PANEL_ZOOM = 1.0

export function clampZoom(val: number): number {
  const rounded = Math.round(val * 100) / 100
  return Math.min(MAX_PANEL_ZOOM, Math.max(MIN_PANEL_ZOOM, rounded))
}

export function formatZoomPercentage(zoom: number): string {
  return `${Math.round(zoom * 100)}%`
}

export function getPanelDisplayName(panelId: string): string {
  switch (panelId) {
    case "reader":
      return "Reader"
    case "note-editor":
      return "Note Editor"
    case "note-preview":
      return "Note Preview"
    case "docked-panel":
      return "Side Panel"
    default:
      return panelId
        .split("-")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ")
  }
}

export type CustomZoomHandler = (action: "in" | "out" | "reset") => boolean

const customZoomHandlers: Record<string, CustomZoomHandler> = {}

export function registerCustomZoomHandler(panelId: string, handler: CustomZoomHandler): () => void {
  customZoomHandlers[panelId] = handler
  return () => {
    if (customZoomHandlers[panelId] === handler) {
      delete customZoomHandlers[panelId]
    }
  }
}

export function getCustomZoomHandler(panelId: string): CustomZoomHandler | undefined {
  return customZoomHandlers[panelId]
}

export function getDefaultPanelForPath(pathname: string): string {
  if (pathname.startsWith("/notes")) {
    return "note-editor"
  }
  return "reader"
}

export interface PanelZoomState {
  zoomLevels: Record<string, number>
  activePanelId: string | null
  setActivePanelId: (id: string | null) => void
  getZoom: (panelId: string) => number
  setZoom: (panelId: string, zoom: number) => number
  zoomIn: (panelId?: string | null) => { panelId: string; zoom: number }
  zoomOut: (panelId?: string | null) => { panelId: string; zoom: number }
  resetZoom: (panelId?: string | null) => { panelId: string; zoom: number }
}

const memoryStorage: Storage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {},
  key: () => null,
  length: 0,
}

export const usePanelZoomStore = create<PanelZoomState>()(
  persist(
    (set, get) => ({
      zoomLevels: {},
      activePanelId: null,

      setActivePanelId: (id) => set({ activePanelId: id }),

      getZoom: (panelId) => {
        const val = get().zoomLevels[panelId]
        return typeof val === "number" && !isNaN(val) ? val : DEFAULT_PANEL_ZOOM
      },

      setZoom: (panelId, zoom) => {
        const clamped = clampZoom(zoom)
        set((state) => ({
          zoomLevels: {
            ...state.zoomLevels,
            [panelId]: clamped,
          },
        }))
        return clamped
      },

      zoomIn: (targetPanelId) => {
        const id = targetPanelId || get().activePanelId || "reader"
        const current = get().getZoom(id)
        const next = clampZoom(current + PANEL_ZOOM_STEP)
        get().setZoom(id, next)
        return { panelId: id, zoom: next }
      },

      zoomOut: (targetPanelId) => {
        const id = targetPanelId || get().activePanelId || "reader"
        const current = get().getZoom(id)
        const next = clampZoom(current - PANEL_ZOOM_STEP)
        get().setZoom(id, next)
        return { panelId: id, zoom: next }
      },

      resetZoom: (targetPanelId) => {
        const id = targetPanelId || get().activePanelId || "reader"
        get().setZoom(id, DEFAULT_PANEL_ZOOM)
        return { panelId: id, zoom: DEFAULT_PANEL_ZOOM }
      },
    }),
    {
      name: "luminary:panel-zoom",
      storage: createJSONStorage(() =>
        typeof window !== "undefined" && window.localStorage ? window.localStorage : memoryStorage
      ),
      partialize: (state) => ({
        zoomLevels: state.zoomLevels,
      }),
    }
  )
)
