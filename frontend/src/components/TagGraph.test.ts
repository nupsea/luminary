/**
 * Vitest unit tests for tag graph utility functions
 *
 * Node environment (no DOM) -- tests pure functions from tagGraphUtils.ts.
 * Tests cover:
 *   1. buildNavigateEvent constructs correct CustomEvent detail
 *   2. colorFromParentTag is deterministic (same input -> same output)
 *   3. Sibling tags with same parent_tag get identical colors
 *   4. Null parent_tag returns first palette color
 *   5. nodeSizeFromCount returns sqrt-proportional value
 *   6. edgeWidthFromWeight scales correctly
 */

import { describe, expect, it } from "vitest"
import {
  buildNavigateEvent,
  colorFromParentTag,
  nodeSizeFromCount,
  edgeWidthFromWeight,
  TAG_GRAPH_PALETTE,
} from "@/lib/tagGraphUtils"

// ---------------------------------------------------------------------------
// AC: buildNavigateEvent constructs correct navigation event
// ---------------------------------------------------------------------------

describe("buildNavigateEvent", () => {
  it("returns a CustomEvent instance", () => {
    const ev = buildNavigateEvent("programming/python")
    expect(ev).toBeInstanceOf(CustomEvent)
  })

  it("event type is luminary:navigate", () => {
    const ev = buildNavigateEvent("science/physics")
    expect(ev.type).toBe("luminary:navigate")
  })

  it("detail.tab is 'notes'", () => {
    const ev = buildNavigateEvent("any-tag")
    expect(ev.detail.tab).toBe("notes")
  })

  it("detail.tagFilter equals the passed tagId", () => {
    const ev = buildNavigateEvent("programming/rust")
    expect(ev.detail.tagFilter).toBe("programming/rust")
  })

  it("preserves hierarchical tag path with slashes", () => {
    const ev = buildNavigateEvent("science/biology/genetics")
    expect(ev.detail.tagFilter).toBe("science/biology/genetics")
  })
})

// ---------------------------------------------------------------------------
// AC: colorFromParentTag is deterministic
// ---------------------------------------------------------------------------

describe("colorFromParentTag", () => {
  it("returns a string starting with #", () => {
    const color = colorFromParentTag("programming")
    expect(color).toMatch(/^#[0-9a-f]{6}$/)
  })

  it("is deterministic: same input always returns same output", () => {
    const c1 = colorFromParentTag("programming")
    const c2 = colorFromParentTag("programming")
    expect(c1).toBe(c2)
  })

  it("sibling tags with the same parent_tag get identical colors", () => {
    const c1 = colorFromParentTag("science")
    const c2 = colorFromParentTag("science")
    expect(c1).toBe(c2)
  })

  it("different parent_tag values can return different colors", () => {
    // Not guaranteed for all pairs, but 'a' and 'zzz' should differ for our hash
    const colors = new Set(["a", "b", "c", "d", "e"].map((p) => colorFromParentTag(p)))
    expect(colors.size).toBeGreaterThan(1)
  })

  it("null parent_tag returns the first palette color", () => {
    expect(colorFromParentTag(null)).toBe(TAG_GRAPH_PALETTE[0])
  })

  it("undefined parent_tag returns the first palette color", () => {
    expect(colorFromParentTag(undefined)).toBe(TAG_GRAPH_PALETTE[0])
  })

  it("empty string parent_tag returns the first palette color", () => {
    expect(colorFromParentTag("")).toBe(TAG_GRAPH_PALETTE[0])
  })

  it("returns a value within the supplied custom palette", () => {
    const customPalette = ["#aabbcc", "#ddeeff"]
    const color = colorFromParentTag("some-tag", customPalette)
    expect(customPalette).toContain(color)
  })
})

// ---------------------------------------------------------------------------
// AC: nodeSizeFromCount returns sqrt-proportional value
// ---------------------------------------------------------------------------

describe("nodeSizeFromCount", () => {
  it("returns a number >= 4", () => {
    expect(nodeSizeFromCount(0)).toBeGreaterThanOrEqual(4)
    expect(nodeSizeFromCount(1)).toBeGreaterThanOrEqual(4)
  })

  it("returns a number <= 24", () => {
    expect(nodeSizeFromCount(10000)).toBeLessThanOrEqual(24)
  })

  it("larger count produces larger size", () => {
    expect(nodeSizeFromCount(100)).toBeGreaterThan(nodeSizeFromCount(4))
  })

  it("returns 4 for count=0 (floor applied)", () => {
    expect(nodeSizeFromCount(0)).toBe(4)
  })
})

// ---------------------------------------------------------------------------
// AC: edgeWidthFromWeight scales proportionally
// ---------------------------------------------------------------------------

describe("edgeWidthFromWeight", () => {
  it("returns minimum 0.5 when maxWeight is 0", () => {
    expect(edgeWidthFromWeight(1, 0)).toBe(0.5)
  })

  it("returns maximum 4 when weight equals maxWeight", () => {
    expect(edgeWidthFromWeight(5, 5)).toBeCloseTo(4)
  })

  it("returns 0.5 when weight is 0", () => {
    expect(edgeWidthFromWeight(0, 10)).toBeCloseTo(0.5)
  })

  it("mid-range weight is between 0.5 and 4", () => {
    const w = edgeWidthFromWeight(5, 10)
    expect(w).toBeGreaterThan(0.5)
    expect(w).toBeLessThan(4)
  })
})
