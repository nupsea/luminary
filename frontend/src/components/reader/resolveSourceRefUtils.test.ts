/**
 * Unit tests for resolveSourceRefUtils (S198).
 *
 * Environment is "node" (no jsdom), so DOM tests use minimal mock objects.
 * resolvePdfFallback tests are purely computational.
 */
import { describe, expect, it } from "vitest"
import { resolveFromDom, resolvePdfFallback } from "./resolveSourceRefUtils"
import type { SectionItem } from "./types"

// Helper to build a minimal SectionItem
function makeSec(id: string, pageStart = 0, pageEnd = 0): SectionItem {
  return {
    id,
    heading: `Section ${id}`,
    level: 1,
    page_start: pageStart,
    page_end: pageEnd,
    section_order: 0,
    preview: "",
    admonition_type: null,
    parent_section_id: null,
  }
}

// ── resolveFromDom ────────────────────────────────────────────────────

describe("resolveFromDom", () => {
  it("returns sectionId from ancestor with data-section-id (simulated ReadView DOM)", () => {
    // Simulate: div[data-section-id="sec-1"] > div > p > textNode
    // In node env, HTMLElement is not available. The utility's fallback checks
    // "dataset" property directly via `"dataset" in node`.
    const sectionDiv = {
      dataset: { sectionId: "sec-1" },
      parentNode: null,
    } as unknown as Node

    const innerDiv = { parentNode: sectionDiv } as unknown as Node
    const paragraph = { parentNode: innerDiv } as unknown as Node
    const textNode = { parentNode: paragraph } as unknown as Node

    const result = resolveFromDom(textNode)
    expect(result).toBe("sec-1")
  })

  it("returns undefined when no ancestor has data-section-id", () => {
    const rootNode = { parentNode: null } as unknown as Node
    const childNode = { parentNode: rootNode } as unknown as Node

    const result = resolveFromDom(childNode)
    expect(result).toBeUndefined()
  })
})

// ── resolvePdfFallback ────────────────────────────────────────────────

describe("resolvePdfFallback", () => {
  it("returns section by page range when sections have real page numbers", () => {
    const sections = [
      makeSec("s1", 1, 5),
      makeSec("s2", 6, 10),
      makeSec("s3", 11, 15),
    ]
    expect(resolvePdfFallback(sections, 3)).toBe("s1")
    expect(resolvePdfFallback(sections, 6)).toBe("s2")
    expect(resolvePdfFallback(sections, 15)).toBe("s3")
  })

  it("uses last-before-current fallback when page is between sections", () => {
    const sections = [
      makeSec("s1", 1, 3),
      makeSec("s2", 7, 10),
    ]
    // Page 5 is between s1 (ends at 3) and s2 (starts at 7)
    // Should fallback to s1 (last section that starts before page 5)
    expect(resolvePdfFallback(sections, 5)).toBe("s1")
  })

  it("returns proportional section when all page_start=0 (PDF parser couldnt map)", () => {
    const sections = [
      makeSec("s1", 0, 0),
      makeSec("s2", 0, 0),
      makeSec("s3", 0, 0),
      makeSec("s4", 0, 0),
    ]
    // With 4 sections and 20 total pages:
    // page 1 -> index 0 -> s1
    // page 10 -> index 1 -> s2
    // page 20 -> index 3 -> s4
    expect(resolvePdfFallback(sections, 1, 20)).toBe("s1")
    expect(resolvePdfFallback(sections, 20, 20)).toBe("s4")
  })

  it("returns first section as ultimate fallback for all-zero without totalPages", () => {
    const sections = [
      makeSec("s1", 0, 0),
      makeSec("s2", 0, 0),
    ]
    // No totalPages provided, so proportional mapping can't work
    expect(resolvePdfFallback(sections, 5)).toBe("s1")
  })

  it("returns undefined for empty sections array", () => {
    expect(resolvePdfFallback([], 1)).toBeUndefined()
  })

  it("handles single section with page_start=0", () => {
    const sections = [makeSec("only", 0, 0)]
    expect(resolvePdfFallback(sections, 5, 10)).toBe("only")
  })
})
