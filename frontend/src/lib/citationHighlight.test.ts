// A citation must be findable in the prose it came from, or say nothing.

import { describe, expect, it } from "vitest"

import {
  citationNeedle,
  longestPresentPrefix,
  stripCitationPrefixes,
} from "./citationHighlight"

// The real shape, from the reported case: the chunk snippet opens with the
// document title, which the transcript prose does not repeat at that point.
const TITLE = "Optimization with Linear Programming (and the Simplex Algorithm), Main Ideas!!!"
const SNIPPET =
  `${TITLE} And the revenue at 8,0,4 is 12. Now, of the three options, the vertex at 12,3,0 ` +
  "results in the largest revenue. So that is where we decide to go. Then"
const PROSE =
  "And the revenue at 8,0,4 is 12. Now, of the three options, the vertex at 12,3,0 results in " +
  "the largest revenue. So that is where we decide to go. Then we repeat the process."

describe("stripCitationPrefixes", () => {
  it("drops a leading document title the prose does not repeat", () => {
    expect(stripCitationPrefixes(SNIPPET, [TITLE])).toMatch(/^And the revenue/)
  })

  it("leaves a snippet alone when it does not carry the prefix", () => {
    expect(stripCitationPrefixes("And the revenue at 8,0,4 is 12.", [TITLE])).toBe(
      "And the revenue at 8,0,4 is 12.",
    )
  })

  it("ignores whitespace and case differences between header and prose", () => {
    expect(stripCitationPrefixes("  THE  TITLE   body text here", ["the title"])).toBe(
      "body text here",
    )
  })
})

describe("longestPresentPrefix", () => {
  it("returns the whole needle when the prose contains it", () => {
    const needle = "And the revenue at 8,0,4 is 12. Now, of the three options"
    expect(longestPresentPrefix(needle, PROSE)).toBe(needle)
  })

  it("shortens to the part that is actually present", () => {
    // The snippet is cut at a fixed length, so its tail can run past the prose
    // or end mid-word. The highlight should still cover what does match.
    const needle = "And the revenue at 8,0,4 is 12. Now, of the three options, the vertex at zzz"
    const got = longestPresentPrefix(needle, PROSE)
    expect(got).toMatch(/^And the revenue at 8,0,4 is 12\./)
    expect(got).not.toContain("zzz")
  })

  it("never ends mid-word", () => {
    const got = longestPresentPrefix("And the revenue at 8,0,4 is 12. Now, of the thr", PROSE)
    expect(got.endsWith("thr")).toBe(false)
  })

  it("returns nothing rather than a match too short to mean anything", () => {
    // A few characters would land on any sentence in the document and point the
    // reader at the wrong place, which is worse than not highlighting.
    expect(longestPresentPrefix("And the", PROSE)).toBe("")
    expect(longestPresentPrefix("nothing here matches at all", PROSE)).toBe("")
  })
})

describe("citationNeedle", () => {
  it("produces something the prose actually contains", () => {
    const needle = citationNeedle({
      section_preview_snippet: SNIPPET,
      document_title: TITLE,
      section_heading: null,
    })
    expect(longestPresentPrefix(needle, PROSE).length).toBeGreaterThan(24)
  })

  it("is empty when the citation carries no snippet", () => {
    expect(citationNeedle({ section_preview_snippet: "", document_title: TITLE })).toBe("")
    expect(citationNeedle({})).toBe("")
  })
})
