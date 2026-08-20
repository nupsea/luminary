import { describe, expect, it } from "vitest"

import { buildBars } from "./activityBars"

describe("buildBars", () => {
  it("keeps a fixed order whatever the week held", () => {
    const { bars } = buildBars({ review: 10, document: 20 })
    expect(bars.map((b) => b.key)).toEqual(["document", "study", "note", "review"])
  })

  it("scales against the largest, not the total", () => {
    // Against the total, a 4% slice is a sliver indistinguishable from nothing.
    const { bars } = buildBars({ document: 1800, study: 60 })
    const byKey = Object.fromEntries(bars.map((b) => [b.key, b.pct]))
    expect(byKey.document).toBe(100)
    expect(byKey.study).toBeGreaterThanOrEqual(3)
  })

  it("gives a recorded activity a visible bar however small", () => {
    // A minute inside a ten-hour week still happened.
    const { bars } = buildBars({ document: 36000, note: 1 })
    expect(bars.find((b) => b.key === "note")?.pct).toBe(3)
  })

  it("draws nothing for an activity with no time", () => {
    // Zero and "too small to see" must not look the same.
    const { bars, total } = buildBars({ document: 100 })
    expect(bars.find((b) => b.key === "note")?.pct).toBe(0)
    expect(total).toBe(100)
  })

  it("survives an empty week", () => {
    const { bars, total } = buildBars({})
    expect(total).toBe(0)
    expect(bars.every((b) => b.pct === 0)).toBe(true)
  })

  it("treats a negative reading as nothing", () => {
    const { total } = buildBars({ document: -5, note: 10 })
    expect(total).toBe(10)
  })
})
