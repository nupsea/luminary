import { describe, expect, it } from "vitest"

import { formatLocus, formatTimestamp, locusOf } from "./locus"

describe("locusOf", () => {
  it("points at the moment for a recording", () => {
    expect(locusOf({ startTime: 862.5, heading: "" })).toEqual({ kind: "time", seconds: 862.5 })
  })

  it("keeps the moment even when a page is also present", () => {
    // A transcript window's section heading is empty by design (I-30), so
    // falling through to it would name nothing at all.
    expect(locusOf({ startTime: 0, page: 3, heading: "Segment 1" })).toEqual({
      kind: "time",
      seconds: 0,
    })
  })

  it("points at the page for a paginated document, carrying the printed label", () => {
    expect(locusOf({ page: 41, pageLabel: "19" })).toEqual({
      kind: "page",
      page: 41,
      label: "19",
    })
  })

  it("falls back to the section heading", () => {
    expect(locusOf({ heading: "Mind Subjective" })).toEqual({
      kind: "section",
      heading: "Mind Subjective",
    })
  })

  it("refuses a source that knows nowhere", () => {
    // The deliberately unresolvable ref: a chunk with no page, no time, no line
    // and no heading. Formatting one anyway is how "p.0" chips shipped.
    expect(locusOf({})).toBeNull()
    expect(locusOf({ page: 0, heading: "   " })).toBeNull()
    expect(locusOf({ startTime: null, page: null, heading: null })).toBeNull()
  })
})

describe("formatTimestamp", () => {
  it("reads as a player's clock", () => {
    expect(formatTimestamp(862.5)).toBe("14:22")
    expect(formatTimestamp(0)).toBe("0:00")
    expect(formatTimestamp(59.9)).toBe("0:59")
    expect(formatTimestamp(3725)).toBe("1:02:05")
  })
})

describe("formatLocus", () => {
  it("renders each kind the way its reader expects", () => {
    expect(formatLocus({ kind: "time", seconds: 862.5 })).toBe("14:22")
    expect(formatLocus({ kind: "page", page: 41, label: "19" })).toBe("p.19")
    expect(formatLocus({ kind: "page", page: 41, label: null })).toBe("p.41")
    expect(formatLocus({ kind: "section", heading: "Ablation Studies" })).toBe("Ablation Studies")
  })

  it("returns null for a source with no locus, and never a placeholder", () => {
    expect(formatLocus(null)).toBeNull()
    expect(formatLocus(locusOf({}))).toBeNull()
  })
})
