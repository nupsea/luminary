import { describe, it, expect, beforeEach } from "vitest"
import {
  usePanelZoomStore,
  clampZoom,
  formatZoomPercentage,
  getPanelDisplayName,
  MIN_PANEL_ZOOM,
  MAX_PANEL_ZOOM,
  DEFAULT_PANEL_ZOOM,
} from "./panelZoomStore"

describe("panelZoomStore", () => {
  beforeEach(() => {
    usePanelZoomStore.setState({
      zoomLevels: {},
      activePanelId: null,
    })
  })

  it("clampZoom clamps values between MIN and MAX and handles rounding", () => {
    expect(clampZoom(0.5)).toBe(MIN_PANEL_ZOOM)
    expect(clampZoom(2.5)).toBe(MAX_PANEL_ZOOM)
    expect(clampZoom(1.1000000000000003)).toBe(1.1)
  })

  it("returns default zoom for unset panels", () => {
    const store = usePanelZoomStore.getState()
    expect(store.getZoom("reader")).toBe(DEFAULT_PANEL_ZOOM)
  })

  it("zooms in and out for a specified panel", () => {
    const store = usePanelZoomStore.getState()
    const { zoom: afterZoomIn } = store.zoomIn("reader")
    expect(afterZoomIn).toBe(1.1)
    expect(usePanelZoomStore.getState().getZoom("reader")).toBe(1.1)

    const { zoom: afterZoomOut } = store.zoomOut("reader")
    expect(afterZoomOut).toBe(1.0)
  })

  it("clamps at maximum and minimum bounds", () => {
    const store = usePanelZoomStore.getState()
    store.setZoom("note-editor", 2.0)
    const { zoom: maxZoom } = store.zoomIn("note-editor")
    expect(maxZoom).toBe(MAX_PANEL_ZOOM)

    store.setZoom("note-editor", 0.7)
    const { zoom: minZoom } = store.zoomOut("note-editor")
    expect(minZoom).toBe(MIN_PANEL_ZOOM)
  })

  it("resets zoom to default 1.0", () => {
    const store = usePanelZoomStore.getState()
    store.setZoom("reader", 1.5)
    expect(store.getZoom("reader")).toBe(1.5)
    const { zoom } = store.resetZoom("reader")
    expect(zoom).toBe(DEFAULT_PANEL_ZOOM)
    expect(store.getZoom("reader")).toBe(DEFAULT_PANEL_ZOOM)
  })

  it("uses activePanelId when target is not specified", () => {
    const store = usePanelZoomStore.getState()
    store.setActivePanelId("note-preview")
    const { panelId, zoom } = store.zoomIn()
    expect(panelId).toBe("note-preview")
    expect(zoom).toBe(1.1)
  })

  it("formats percentages and panel display names", () => {
    expect(formatZoomPercentage(1.1)).toBe("110%")
    expect(formatZoomPercentage(0.9)).toBe("90%")
    expect(getPanelDisplayName("reader")).toBe("Reader")
    expect(getPanelDisplayName("note-editor")).toBe("Note Editor")
    expect(getPanelDisplayName("note-preview")).toBe("Note Preview")
    expect(getPanelDisplayName("docked-panel")).toBe("Side Panel")
  })
})
