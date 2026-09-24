import { describe, it, expect, beforeEach } from "vitest"
import { usePanelZoomStore } from "@/store/panelZoomStore"

describe("PanelZoomResetButton logic", () => {
  beforeEach(() => {
    usePanelZoomStore.setState({
      zoomLevels: {},
      activePanelId: null,
    })
  })

  it("checks whether reset is needed based on zoom scale", () => {
    const store = usePanelZoomStore.getState()
    expect(store.getZoom("reader")).toBe(1.0)

    store.setZoom("reader", 1.2)
    expect(usePanelZoomStore.getState().getZoom("reader")).toBe(1.2)

    const { zoom } = usePanelZoomStore.getState().resetZoom("reader")
    expect(zoom).toBe(1.0)
    expect(usePanelZoomStore.getState().getZoom("reader")).toBe(1.0)
  })
})
