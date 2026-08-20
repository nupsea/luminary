import { describe, expect, it } from "vitest"

import { ACTIVITY_SLICES, buildWedges, slicePath } from "./activityPie"

describe("buildWedges", () => {
  it("draws nothing when no time was recorded", () => {
    expect(buildWedges({}, 36, 36, 30)).toEqual({ wedges: [], total: 0 })
    expect(buildWedges({ document: 0, note: 0 }, 36, 36, 30).total).toBe(0)
  })

  it("skips an activity with no time rather than drawing a hairline", () => {
    const { wedges } = buildWedges({ document: 600, review: 300 }, 36, 36, 30)
    expect(wedges.map((w) => w.key)).toEqual(["document", "review"])
  })

  it("draws a single activity as a circle, not an arc", () => {
    // An arc whose start and end coincide renders as nothing at all, so a week
    // spent entirely on one activity would show an empty chart.
    const { wedges, total } = buildWedges({ document: 900 }, 36, 36, 30)
    expect(wedges).toHaveLength(1)
    expect(wedges[0].path).toBeNull()
    expect(total).toBe(900)
  })

  it("keeps the fixed hue order regardless of which activities are present", () => {
    // Colour follows the entity, never its rank: a quiet week on notes must not
    // repaint reading with the notes hue.
    const all = buildWedges({ document: 1, note: 1, review: 1, study: 1 }, 36, 36, 30)
    const some = buildWedges({ document: 1, study: 1 }, 36, 36, 30)
    const colourFor = (ws: typeof all.wedges, key: string) => ws.find((w) => w.key === key)?.colour
    expect(colourFor(some.wedges, "document")).toBe(colourFor(all.wedges, "document"))
    expect(colourFor(some.wedges, "study")).toBe(colourFor(all.wedges, "study"))
  })

  it("sums to the whole circle", () => {
    const { total } = buildWedges({ document: 100, note: 200, review: 300 }, 36, 36, 30)
    expect(total).toBe(600)
  })

  it("treats a negative reading as nothing", () => {
    const { wedges, total } = buildWedges({ document: -50, note: 100 }, 36, 36, 30)
    expect(total).toBe(100)
    expect(wedges.map((w) => w.key)).toEqual(["note"])
  })
})

describe("slicePath", () => {
  it("marks the arc as large only past a half turn", () => {
    const small = slicePath(36, 36, 30, 0, Math.PI / 2)
    const large = slicePath(36, 36, 30, 0, Math.PI * 1.5)
    expect(small).toContain("A 30 30 0 0 1")
    expect(large).toContain("A 30 30 0 1 1")
  })

  it("closes back to the centre so the wedge is filled", () => {
    expect(slicePath(36, 36, 30, 0, 1)).toMatch(/^M 36 36 L .* Z$/)
  })
})

describe("ACTIVITY_SLICES", () => {
  it("gives every activity a distinct hue", () => {
    const hues = ACTIVITY_SLICES.map((s) => s.colour)
    expect(new Set(hues).size).toBe(hues.length)
  })
})
