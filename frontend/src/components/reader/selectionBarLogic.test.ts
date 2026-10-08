import { describe, expect, it } from "vitest"
import { BAR_HALF_WIDTH, BAR_HEIGHT, explainModeFor, placeBar } from "./selectionBarLogic"

describe("explainModeFor", () => {
  it("defines a word or a short term", () => {
    expect(explainModeFor("lakehouse")).toBe("define")
    expect(explainModeFor("  Lakehouse, ")).toBe("define")
    expect(explainModeFor("data lakehouse architecture")).toBe("define")
    expect(explainModeFor("write-ahead log (WAL).")).toBe("define")
  })

  it("simplifies a sentence or a long phrase", () => {
    expect(explainModeFor("The lakehouse stores tables. It is open.")).toBe("plain")
    expect(explainModeFor("Spark reads it; Trino queries it")).toBe("plain")
    expect(explainModeFor("a format that combines the lake and the warehouse")).toBe("plain")
  })
})

const viewport = { width: 1200, height: 800 }
const reader = { top: 60, bottom: 800, left: 0, right: 900 }

describe("placeBar", () => {
  it("sits above the selection when there is room", () => {
    const p = placeBar({ top: 300, bottom: 320, left: 400, right: 500 }, reader, viewport)
    expect(p).toEqual({ top: 292, left: 450, side: "above" })
  })

  it("flips below a selection at the top of the reader", () => {
    const p = placeBar({ top: 70, bottom: 90, left: 400, right: 500 }, reader, viewport)
    expect(p?.side).toBe("below")
    expect(p?.top).toBe(98)
  })

  it("stays inside the reader for a selection taller than it", () => {
    const p = placeBar({ top: -500, bottom: 2000, left: 0, right: 900 }, reader, viewport)
    expect(p?.side).toBe("below")
    expect(p!.top).toBeGreaterThanOrEqual(reader.top)
    expect(p!.top).toBeLessThanOrEqual(viewport.height - BAR_HEIGHT)
  })

  it("keeps the bar on screen near the edges", () => {
    const p = placeBar({ top: 300, bottom: 320, left: 0, right: 10 }, reader, viewport)
    expect(p?.left).toBe(BAR_HALF_WIDTH)
  })

  it("hides once the selection scrolls out of the reader", () => {
    expect(placeBar({ top: 10, bottom: 40, left: 0, right: 10 }, reader, viewport)).toBeNull()
    expect(placeBar({ top: 900, bottom: 920, left: 0, right: 10 }, reader, viewport)).toBeNull()
  })
})
