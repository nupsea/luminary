/**
 * Vitest unit tests for ClozeCard parsing logic (S154).
 * Tests the pure `parseClozeSegments` function exported from ClozeCard.tsx.
 */

import { describe, expect, it } from "vitest"
import { parseClozeSegments } from "./ClozeCard"

describe("parseClozeSegments", () => {
  it("parses two blanks correctly", () => {
    const segments = parseClozeSegments("{{X}} and {{Y}} are different")
    const blanks = segments.filter((s) => s.type === "blank")
    expect(blanks).toHaveLength(2)
    expect((blanks[0] as { type: "blank"; term: string }).term).toBe("X")
    expect((blanks[1] as { type: "blank"; term: string }).term).toBe("Y")
  })

  it("returns no blanks for plain text", () => {
    const segments = parseClozeSegments("No blanks here")
    expect(segments.every((s) => s.type === "text")).toBe(true)
  })

  it("handles single blank", () => {
    const segments = parseClozeSegments("A {{generator}} uses yield")
    const blanks = segments.filter((s) => s.type === "blank")
    expect(blanks).toHaveLength(1)
    expect((blanks[0] as { type: "blank"; term: string }).term).toBe("generator")
  })

  it("preserves text segments around blanks", () => {
    const segments = parseClozeSegments("A {{generator}} uses {{yield}}")
    const texts = segments.filter((s) => s.type === "text").map((s) => (s as { type: "text"; content: string }).content)
    expect(texts).toContain("A ")
    expect(texts).toContain(" uses ")
  })

  it("handles empty string", () => {
    const segments = parseClozeSegments("")
    expect(segments).toHaveLength(1)
    expect(segments[0]).toEqual({ type: "text", content: "" })
  })
})
