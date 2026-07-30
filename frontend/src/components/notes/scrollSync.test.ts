import { describe, expect, it } from "vitest"
import {
  interpolate,
  lineToOffset,
  normalizeAnchors,
  offsetToLine,
  type SourceAnchor,
} from "./scrollSync"

describe("interpolate", () => {
  const points = [
    { x: 0, y: 0 },
    { x: 10, y: 100 },
    { x: 20, y: 150 },
  ]

  it("clamps outside the covered range", () => {
    expect(interpolate(-5, points)).toBe(0)
    expect(interpolate(99, points)).toBe(150)
  })

  it("returns exact values at the anchors", () => {
    expect(interpolate(10, points)).toBe(100)
  })

  it("interpolates within a segment using that segment's own slope", () => {
    // The second segment is half as steep as the first; a global ratio would
    // put x=15 at 112.5 instead of 125.
    expect(interpolate(5, points)).toBe(50)
    expect(interpolate(15, points)).toBe(125)
  })

  it("survives an empty or degenerate input", () => {
    expect(interpolate(3, [])).toBe(0)
    expect(interpolate(3, [{ x: 3, y: 7 }])).toBe(7)
    expect(
      interpolate(3, [
        { x: 3, y: 7 },
        { x: 3, y: 9 },
      ]),
    ).toBe(7)
  })
})

describe("normalizeAnchors", () => {
  it("adds the synthetic start and end so the range is total", () => {
    const anchors = normalizeAnchors([{ line: 4, top: 40 }], 10, 400)
    expect(anchors[0]).toEqual({ line: 1, top: 0 })
    expect(anchors[anchors.length - 1]).toEqual({ line: 11, top: 400 })
  })

  it("drops blocks that would invert the mapping", () => {
    const raw: SourceAnchor[] = [
      { line: 1, top: 0 },
      { line: 5, top: 50 },
      { line: 3, top: 70 }, // line goes backwards
      { line: 9, top: 40 }, // offset goes backwards from the last kept anchor
      { line: 12, top: 120 },
    ]
    expect(normalizeAnchors(raw, 12, 200).map((a) => a.line)).toEqual([1, 5, 12, 13])
  })

  it("ignores non-finite values", () => {
    const raw = [
      { line: 1, top: 0 },
      { line: Number.NaN, top: 10 },
      { line: 6, top: Number.NaN },
      { line: 8, top: 80 },
    ]
    expect(normalizeAnchors(raw, 8, 160).map((a) => a.line)).toEqual([1, 8, 9])
  })

  it("returns nothing when the preview exposed no anchors", () => {
    expect(normalizeAnchors([], 10, 400)).toEqual([])
  })

  it("does not append an end anchor that would sit above the last block", () => {
    // A pane scrolled to its limit can report a content end below the final
    // block's measured top; appending it would invert the mapping.
    const anchors = normalizeAnchors([{ line: 4, top: 500 }], 10, 100)
    expect(anchors[anchors.length - 1]).toEqual({ line: 4, top: 500 })
  })
})

describe("lineToOffset / offsetToLine", () => {
  // A tight source block that renders tall (a list becoming spaced paragraphs)
  // followed by a long paragraph that renders short.
  const anchors: SourceAnchor[] = [
    { line: 1, top: 0 },
    { line: 10, top: 100 },
    { line: 14, top: 600 },
    { line: 40, top: 700 },
  ]

  it("round-trips a line through an offset and back", () => {
    for (const line of [1, 5, 10, 12, 14, 30, 40]) {
      expect(offsetToLine(lineToOffset(line, anchors), anchors)).toBeCloseTo(line, 6)
    }
  })

  it("tracks the steep region instead of the document average", () => {
    // Line 12 is halfway through the block that renders tall: 350px in.
    // The global-ratio mapping this replaces would have produced ~193px.
    expect(lineToOffset(12, anchors)).toBe(350)
  })

  it("pins the ends", () => {
    expect(lineToOffset(0, anchors)).toBe(0)
    expect(lineToOffset(999, anchors)).toBe(700)
  })

  it("falls back to offset 0 when there are no anchors", () => {
    expect(lineToOffset(7, [])).toBe(0)
    expect(offsetToLine(70, [])).toBe(0)
  })
})
