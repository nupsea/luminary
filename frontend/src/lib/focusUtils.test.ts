import { describe, expect, it } from "vitest"
import {
  formatMmSs,
  inferSurfaceFromPath,
  isValidMinutes,
} from "./focusUtils"

describe("inferSurfaceFromPath", () => {
  it("maps root to read (Learning tab)", () => {
    expect(inferSurfaceFromPath("/")).toBe("read")
    expect(inferSurfaceFromPath("")).toBe("read")
  })

  it("maps /study to recall", () => {
    expect(inferSurfaceFromPath("/study")).toBe("recall")
    expect(inferSurfaceFromPath("/study/")).toBe("recall")
  })

  it("maps /notes to write", () => {
    expect(inferSurfaceFromPath("/notes")).toBe("write")
  })

  it("maps /chat to explore", () => {
    expect(inferSurfaceFromPath("/chat")).toBe("explore")
  })

  it("maps Viz/Monitoring/Progress/Admin to none", () => {
    expect(inferSurfaceFromPath("/viz")).toBe("none")
    expect(inferSurfaceFromPath("/monitoring")).toBe("none")
    expect(inferSurfaceFromPath("/progress")).toBe("none")
    expect(inferSurfaceFromPath("/admin")).toBe("none")
  })

  it("strips query strings before matching", () => {
    expect(inferSurfaceFromPath("/?doc=abc")).toBe("read")
    expect(inferSurfaceFromPath("/study?deck=xyz")).toBe("recall")
  })
})

describe("formatMmSs", () => {
  it("zero-pads seconds and minutes", () => {
    expect(formatMmSs(0)).toBe("00:00")
    expect(formatMmSs(5)).toBe("00:05")
    expect(formatMmSs(65)).toBe("01:05")
  })

  it("formats 25 minutes as 25:00", () => {
    expect(formatMmSs(25 * 60)).toBe("25:00")
  })

  it("clamps negative values to zero", () => {
    expect(formatMmSs(-1)).toBe("00:00")
    expect(formatMmSs(-100)).toBe("00:00")
  })

  it("handles fractional input via floor", () => {
    expect(formatMmSs(59.9)).toBe("00:59")
  })
})

describe("isValidMinutes", () => {
  it("accepts 1..120", () => {
    expect(isValidMinutes(1)).toBe(true)
    expect(isValidMinutes(25)).toBe(true)
    expect(isValidMinutes(120)).toBe(true)
  })

  it("rejects non-integer, zero, negative, and > 120", () => {
    expect(isValidMinutes(0)).toBe(false)
    expect(isValidMinutes(-1)).toBe(false)
    expect(isValidMinutes(121)).toBe(false)
    expect(isValidMinutes(1.5)).toBe(false)
    expect(isValidMinutes(NaN)).toBe(false)
  })
})
