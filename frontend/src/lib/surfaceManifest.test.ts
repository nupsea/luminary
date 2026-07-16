import { afterEach, describe, expect, it, vi } from "vitest"

async function loadWithMode(mode: string) {
  vi.resetModules()
  vi.stubEnv("VITE_LUMINARY_MODE", mode)
  return import("./surfaceManifest")
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe("surfaceManifest", () => {
  it("public mode hides full-mode surfaces", async () => {
    const m = await loadWithMode("public")
    const ids = m.visibleSurfaces().map((s) => s.id)
    expect(ids).toContain("library")
    expect(ids).not.toContain("map")
    expect(ids).not.toContain("feynman")
    expect(ids).not.toContain("quality_dashboard")
  })

  it("full mode shows everything", async () => {
    const m = await loadWithMode("full")
    const ids = m.visibleSurfaces().map((s) => s.id)
    expect(ids).toContain("map")
    expect(ids).toContain("feynman")
    expect(ids).toContain("quality_dashboard")
  })

  it("map is a nav_tab in the full-mode learner rail (not the dev rail)", async () => {
    const m = await loadWithMode("full")
    const map = m.navTabs().find((s) => s.id === "map")
    expect(map).toBeDefined()
    expect(map?.rail).toBeUndefined()
  })

  it("dev-rail tabs are exactly Quality/Admin/Monitoring in full mode", async () => {
    const m = await loadWithMode("full")
    const devRail = m.navTabs().filter((s) => s.rail === "dev").map((s) => s.id)
    expect(devRail.sort()).toEqual(["admin", "monitoring", "quality_dashboard"])
  })

  it("navTabs returns only nav_tab surfaces", async () => {
    const m = await loadWithMode("public")
    expect(m.navTabs().every((s) => s.kind === "nav_tab")).toBe(true)
  })

  it("isSurfaceVisible gates cross-surface entry points per mode", async () => {
    const pub = await loadWithMode("public")
    expect(pub.isSurfaceVisible("map")).toBe(false)
    expect(pub.isSurfaceVisible("blog")).toBe(false)
    const full = await loadWithMode("full")
    expect(full.isSurfaceVisible("map")).toBe(true)
    expect(full.isSurfaceVisible("blog")).toBe(true)
  })
})
