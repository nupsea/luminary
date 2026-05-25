import { afterEach, describe, expect, it, vi } from "vitest"

async function loadWithTier(tier: string) {
  vi.resetModules()
  vi.stubEnv("VITE_SURFACE_TIER", tier)
  return import("./surfaceManifest")
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe("surfaceManifest", () => {
  it("public tier hides labs and dev surfaces", async () => {
    const m = await loadWithTier("public")
    const ids = m.visibleSurfaces(new Set()).map((s) => s.id)
    expect(ids).toContain("library")
    expect(ids).not.toContain("feynman")
    expect(ids).not.toContain("quality_dashboard")
  })

  it("public tier stays minimal — labs are not revealable even if toggled on", async () => {
    const m = await loadWithTier("public")
    const ids = m.visibleSurfaces(new Set(["feynman"])).map((s) => s.id)
    expect(ids).not.toContain("feynman")
  })

  it("labs tier gates labs surfaces on the per-install toggle", async () => {
    const m = await loadWithTier("labs")
    expect(m.visibleSurfaces(new Set()).map((s) => s.id)).not.toContain("feynman")
    expect(m.visibleSurfaces(new Set(["feynman"])).map((s) => s.id)).toContain("feynman")
    // dev surfaces never compile into a labs bundle
    expect(m.visibleSurfaces(new Set(["feynman"])).map((s) => s.id)).not.toContain("quality_dashboard")
  })

  it("dev tier shows everything and ignores the labs toggle", async () => {
    const m = await loadWithTier("dev")
    const ids = m.visibleSurfaces(new Set()).map((s) => s.id)
    expect(ids).toContain("feynman")
    expect(ids).toContain("quality_dashboard")
  })

  it("navTabs returns only nav_tab surfaces", async () => {
    const m = await loadWithTier("public")
    expect(m.navTabs(new Set()).every((s) => s.kind === "nav_tab")).toBe(true)
  })

  it("findLabsSurfaceByRoute only matches labs-tier routes", async () => {
    const m = await loadWithTier("public")
    expect(m.findLabsSurfaceByRoute("/library")).toBeUndefined()
  })
})
