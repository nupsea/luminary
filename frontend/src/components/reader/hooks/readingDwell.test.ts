import { describe, it, expect } from "vitest"

import {
  DWELL_MS,
  isBeingRead,
  SECTION_VISIBLE_RATIO,
  THRESHOLDS,
  VIEWPORT_COVERED_RATIO,
  type VisibilitySample,
} from "./readingDwell"

const sample = (over: Partial<VisibilitySample> = {}): VisibilitySample => ({
  isIntersecting: true,
  intersectionRatio: 0,
  intersectionHeight: 0,
  rootHeight: 900,
  ...over,
})

describe("isBeingRead", () => {
  it("is false when the section is off screen", () => {
    expect(isBeingRead(sample({ isIntersecting: false, intersectionRatio: 1 }))).toBe(false)
  })

  it("counts a short section that is half visible", () => {
    expect(isBeingRead(sample({ intersectionRatio: 0.5, intersectionHeight: 100 }))).toBe(true)
  })

  it("does not count a section barely peeking in", () => {
    expect(isBeingRead(sample({ intersectionRatio: 0.1, intersectionHeight: 40 }))).toBe(false)
  })

  it("counts a section too tall to ever be half visible but filling the screen", () => {
    // The measured case: 5,063,040 characters in one section. Its ratio can
    // never reach 0.5, so a ratio-only test never fires and the section is
    // never recorded as read however long it is on screen.
    expect(
      isBeingRead(sample({ intersectionRatio: 0.02, intersectionHeight: 900, rootHeight: 900 })),
    ).toBe(true)
  })

  it("does not count a tall section that only covers a sliver of the viewport", () => {
    expect(
      isBeingRead(sample({ intersectionRatio: 0.02, intersectionHeight: 90, rootHeight: 900 })),
    ).toBe(false)
  })

  it("does not divide by a zero-height root", () => {
    expect(
      isBeingRead(sample({ intersectionRatio: 0.1, intersectionHeight: 50, rootHeight: 0 })),
    ).toBe(false)
  })
})

describe("thresholds", () => {
  it("dwell is longer than a scroll-past and shorter than reading a paragraph", () => {
    // ~1s is a fast scroll on the way elsewhere; ~15s is a 50-word paragraph at
    // the 200 wpm convention. The value must sit strictly between them.
    expect(DWELL_MS).toBeGreaterThan(1000)
    expect(DWELL_MS).toBeLessThan(15000)
  })

  it("reports intermediate ratios so a tall section fires a callback at all", () => {
    expect(THRESHOLDS[0]).toBe(0)
    expect(THRESHOLDS.some((t) => t > 0 && t < SECTION_VISIBLE_RATIO)).toBe(true)
  })

  it("both visibility rules are real fractions", () => {
    for (const r of [SECTION_VISIBLE_RATIO, VIEWPORT_COVERED_RATIO]) {
      expect(r).toBeGreaterThan(0)
      expect(r).toBeLessThanOrEqual(1)
    }
  })
})
