// A citation resolved into ids and words, without a view in sight.

import { describe, expect, it } from "vitest"

import { buildCitationTarget, stateValueToWords, stripCitationPrefixes, targetToStateValue, wordsPresentIn } from "./target"

const TITLE = "Optimization with Linear Programming (and the Simplex Algorithm), Main Ideas!!!"

describe("stripCitationPrefixes", () => {
  it("drops a leading document title the prose does not repeat", () => {
    expect(stripCitationPrefixes(`${TITLE} And the revenue`, [TITLE])).toBe("And the revenue")
  })

  it("ignores whitespace and case differences", () => {
    expect(stripCitationPrefixes("  THE  TITLE   body", ["the title"])).toBe("body")
  })

  it("leaves a snippet that does not carry the prefix alone", () => {
    expect(stripCitationPrefixes("And the revenue", [TITLE])).toBe("And the revenue")
  })
})

describe("buildCitationTarget", () => {
  it("carries every address a view might use", () => {
    const t = buildCitationTarget({
      chunk_id: "c1",
      document_id: "d1",
      document_title: TITLE,
      section_id: "s1",
      section_heading: "",
      pdf_page_number: 7,
      section_preview_snippet: `${TITLE} And the revenue at 8,0,4 is 12.`,
    })
    expect(t).toMatchObject({ documentId: "d1", chunkId: "c1", sectionId: "s1", page: 7 })
    expect(t.words.slice(0, 3)).toEqual(["And", "the", "revenue"])
  })

  it("yields no words when there is no snippet, rather than a false locator", () => {
    expect(buildCitationTarget({ chunk_id: "c1" }).words).toEqual([])
    expect(buildCitationTarget({ section_preview_snippet: "   " }).words).toEqual([])
  })
})

describe("wordsPresentIn", () => {
  it("returns only what this text holds, so a straddling chunk still marks", () => {
    const t = buildCitationTarget({ section_preview_snippet: "alpha beta gamma delta epsilon zeta" })
    expect(wordsPresentIn(t, "beta gamma delta epsilon and more").join(" "))
      .toBe("beta gamma delta epsilon")
  })

  it("returns nothing for text that holds none of it", () => {
    const t = buildCitationTarget({ section_preview_snippet: "alpha beta gamma delta epsilon" })
    expect(wordsPresentIn(t, "entirely unrelated prose here")).toEqual([])
  })
})

describe("router state round trip", () => {
  it("survives being carried through navigation", () => {
    const t = buildCitationTarget({ section_preview_snippet: "some cited passage text here" })
    expect(stateValueToWords(targetToStateValue(t))).toEqual(t.words)
  })

  it("treats a missing value as no citation", () => {
    expect(stateValueToWords(null)).toEqual([])
    expect(stateValueToWords("")).toEqual([])
  })
})
