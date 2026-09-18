// A citation resolved into ids and words, without a view in sight.

import { describe, expect, it } from "vitest"

import {
  buildCitationTarget,
  resolveInPlaceCitation,
  stateValueToWords,
  stripCitationPrefixes,
  targetToStateValue,
  wordsPresentIn,
} from "./target"

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

describe("resolveInPlaceCitation", () => {
  // #137-adjacent: a citation to "DDIA / Batch and Stream Processing p.495"
  // was landing the PDF viewer on the table of contents (p.14) instead --
  // PDFViewer's own `initialPage` prop is fixed at mount, so a click later in
  // the session had no current page to search first and fell back to a full
  // scan that stopped at the heading's other, much shorter appearance in the
  // ToC before ever reaching the real page. The page must travel with the
  // click, not sit in a prop that never updates after mount.
  const arrival = ["some", "arrival", "words"]

  it("has no page when the reader has not clicked a citation yet", () => {
    expect(resolveInPlaceCitation(null, arrival)).toEqual({ words: arrival, page: null })
  })

  it("carries the clicked citation's own page, not the mount-time page", () => {
    const clicked = { against: arrival, words: ["cited", "prose"], page: 517 }
    expect(resolveInPlaceCitation(clicked, arrival)).toEqual({ words: ["cited", "prose"], page: 517 })
  })

  it("drops a stale click once a new arrival supersedes it", () => {
    const staleClick = { against: ["old", "arrival"], words: ["stale"], page: 517 }
    expect(resolveInPlaceCitation(staleClick, arrival)).toEqual({ words: arrival, page: null })
  })

  it("resets the page to null for a citation with no page of its own", () => {
    const clicked = { against: arrival, words: ["heading", "only"], page: null }
    expect(resolveInPlaceCitation(clicked, arrival)).toEqual({ words: ["heading", "only"], page: null })
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
