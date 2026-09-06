// A citation must be findable in the prose it came from, or say nothing.

import { describe, expect, it } from "vitest"

import {
  citationNeedle,
  longestPresentRun,
  markWords,
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

describe("longestPresentRun", () => {
  it("returns the whole needle when the prose contains it", () => {
    const needle = "And the revenue at 8,0,4 is 12. Now, of the three options"
    expect(longestPresentRun(needle, PROSE).join(" ")).toBe(needle)
  })

  it("shortens to the part that is actually present", () => {
    // The snippet is cut at a fixed length, so its tail can run past the prose
    // or end mid-word. The highlight should still cover what does match.
    const needle = "And the revenue at 8,0,4 is 12. Now, of the three options, the vertex at zzz"
    const got = longestPresentRun(needle, PROSE).join(" ")
    expect(got).toMatch(/^And the revenue at 8,0,4 is 12\./)
    expect(got).not.toContain("zzz")
  })

  it("never ends mid-word", () => {
    const got = longestPresentRun("And the revenue at 8,0,4 is 12. Now, of the thr", PROSE).join(" ")
    expect(got.endsWith("thr")).toBe(false)
  })

  it("returns nothing rather than a match too short to mean anything", () => {
    // A few characters would land on any sentence in the document and point the
    // reader at the wrong place, which is worse than not highlighting.
    expect(longestPresentRun("And the", PROSE).join(" ")).toBe("")
    expect(longestPresentRun("nothing here matches at all", PROSE).join(" ")).toBe("")
  })
})

describe("citationNeedle", () => {
  it("produces something the prose actually contains", () => {
    const needle = citationNeedle({
      section_preview_snippet: SNIPPET,
      document_title: TITLE,
      section_heading: null,
    })
    expect(longestPresentRun(needle, PROSE).join(" ").length).toBeGreaterThan(24)
  })

  it("is empty when the citation carries no snippet", () => {
    expect(citationNeedle({ section_preview_snippet: "", document_title: TITLE })).toBe("")
    expect(citationNeedle({})).toBe("")
  })
})

// The two failures found by driving the real app, each pinned to its cause.

describe("leading material the prose does not contain", () => {
  it("skips a bracketed breadcrumb the chunk text carries", () => {
    // Real citation: the chunk is stored with "[Doc > Section]" in front, which
    // the article body never contains. A matcher that only trims the tail keeps
    // that prefix and finds nothing at all.
    const snippet =
      "[Introducing Contextual Retrieval > Get the developer newsletter] " +
      "We experimented across various knowledge domains"
    const prose = "We experimented across various knowledge domains (codebases, fiction)."
    expect(longestPresentRun(snippet, prose).join(" ")).toBe(
      "We experimented across various knowledge domains",
    )
  })
})

describe("markWords", () => {
  it("marks across the paragraph breaks the chunk text collapsed", () => {
    // The failure that made the mark silently never appear: the snippet reads
    // "traps? GUEST: Two" while the section holds "traps?\n\nGUEST: Two".
    const raw = "HOST: Any evaluation traps?\n\nGUEST: Two big ones."
    const words = ["evaluation", "traps?", "GUEST:", "Two"]
    const out = markWords(raw, words, "mk")
    expect(out).toContain('<mark class="mk">')
    expect(out).toContain("traps?\n\nGUEST:")
  })

  it("leaves the content alone when there is nothing to mark", () => {
    expect(markWords("some prose", [], "mk")).toBe("some prose")
  })

  it("skips a match that would split existing markup", () => {
    // applyHighlights may already have wrapped a saved annotation; splitting one
    // would corrupt the HTML.
    const raw = 'a <mark class="ann">b</mark> c'
    expect(markWords(raw, ["a", "b", "c"], "mk")).toBe(raw)
  })
})
