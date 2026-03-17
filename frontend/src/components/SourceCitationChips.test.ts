/**
 * Vitest unit tests for SourceCitationChips logic (S157).
 * Tests the pure `deduplicateCitations` function exported from SourceCitationChips.tsx.
 *
 * The number of items returned by deduplicateCitations maps directly to the
 * number of Badge elements rendered by SourceCitationChips in the DOM.
 */

import { describe, expect, it } from "vitest"
import { deduplicateCitations } from "./SourceCitationChips"
import type { SourceCitation } from "./SourceCitationChips"

function makeCitation(overrides: Partial<SourceCitation> & { chunk_id: string }): SourceCitation {
  return {
    document_id: "doc1",
    document_title: "Test Book",
    section_id: null,
    section_heading: "",
    pdf_page_number: null,
    section_preview_snippet: "",
    ...overrides,
  }
}

describe("SourceCitationChips", () => {
  it("with 2 distinct citations renders 2 Badge elements", () => {
    const result = deduplicateCitations([
      makeCitation({ chunk_id: "c1", section_id: "s1", section_heading: "Intro" }),
      makeCitation({ chunk_id: "c2", section_id: "s2", section_heading: "Chapter 1" }),
    ])
    expect(result).toHaveLength(2)
  })

  it("with empty array renders null (returns 0 items)", () => {
    const result = deduplicateCitations([])
    expect(result).toHaveLength(0)
  })

  it("deduplicates by section_id — keeps first occurrence", () => {
    const result = deduplicateCitations([
      makeCitation({ chunk_id: "c1", section_id: "s1", section_heading: "Intro" }),
      makeCitation({ chunk_id: "c2", section_id: "s1", section_heading: "Intro (duplicate)" }),
    ])
    expect(result).toHaveLength(1)
    expect(result[0].chunk_id).toBe("c1")
  })

  it("treats null section_id chunks as distinct by chunk_id", () => {
    const result = deduplicateCitations([
      makeCitation({ chunk_id: "c1", section_id: null }),
      makeCitation({ chunk_id: "c2", section_id: null }),
    ])
    expect(result).toHaveLength(2)
  })

  it("mixes section_id and null — deduplicates only section_id matches", () => {
    const result = deduplicateCitations([
      makeCitation({ chunk_id: "c1", section_id: "s1" }),
      makeCitation({ chunk_id: "c2", section_id: "s1" }),  // dup
      makeCitation({ chunk_id: "c3", section_id: null }),
    ])
    expect(result).toHaveLength(2)
  })
})
