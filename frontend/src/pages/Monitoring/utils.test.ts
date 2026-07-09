import { describe, expect, it } from "vitest"

import { formatCount, formatDuration } from "./utils"

describe("formatDuration", () => {
  it("renders sub-second spans in ms", () => {
    expect(formatDuration(0)).toBe("0.0 ms")
    expect(formatDuration(42.55)).toBe("42.5 ms")
    expect(formatDuration(999.9)).toBe("999.9 ms")
  })

  it("renders 1s..60s spans in seconds", () => {
    expect(formatDuration(1000)).toBe("1.00 s")
    expect(formatDuration(1534)).toBe("1.53 s")
    expect(formatDuration(59999)).toBe("60.00 s")
  })

  it("renders >=60s spans in minutes", () => {
    expect(formatDuration(60000)).toBe("1.0 min")
    expect(formatDuration(90000)).toBe("1.5 min")
  })
})

describe("formatCount", () => {
  it("keeps small numbers verbatim", () => {
    expect(formatCount(0)).toBe("0")
    expect(formatCount(999)).toBe("999")
  })

  it("abbreviates thousands and millions", () => {
    expect(formatCount(1_534)).toBe("1.5k")
    expect(formatCount(45_120)).toBe("45k")
    expect(formatCount(2_400_000)).toBe("2.4M")
  })
})
