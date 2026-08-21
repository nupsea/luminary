import { describe, it, expect } from "vitest"

import {
  applySearchTerm,
  orderHitsByDocument,
  SEARCH_MARK_CLASS,
  widenedListLimit,
} from "./searchHighlight"

describe("applySearchTerm", () => {
  it("marks every occurrence, case-insensitively, preserving original casing", () => {
    const out = applySearchTerm("Memory and memory and MEMORY", "memory")
    expect(out.match(/<mark/g)).toHaveLength(3)
    expect(out).toContain(`<mark class="${SEARCH_MARK_CLASS}">Memory</mark>`)
    expect(out).toContain(`<mark class="${SEARCH_MARK_CLASS}">MEMORY</mark>`)
  })

  it("leaves content untouched for a term below the length floor", () => {
    const body = "a section about a topic"
    expect(applySearchTerm(body, "a")).toBe(body)
    expect(applySearchTerm(body, "")).toBe(body)
    expect(applySearchTerm(body, "   ")).toBe(body)
  })

  it("never matches inside an existing annotation mark's attributes", () => {
    // applyHighlights has already run: the word "mark" appears inside the tag
    // itself. Marking there would produce nested, broken markup.
    const withAnnotation = `before <mark class="bg-yellow-200 rounded-sm px-0.5">kept text</mark> after`
    const out = applySearchTerm(withAnnotation, "mark")
    expect(out).toBe(withAnnotation)
  })

  it("still marks body text that sits alongside an annotation mark", () => {
    const withAnnotation = `alpha <mark class="bg-yellow-200">beta</mark> alpha`
    const out = applySearchTerm(withAnnotation, "alpha")
    expect(out.match(/<mark class="bg-sky/g)).toHaveLength(2)
    // The annotation mark survives intact.
    expect(out).toContain(`<mark class="bg-yellow-200">beta</mark>`)
  })

  it("returns the input unchanged when the term is absent", () => {
    expect(applySearchTerm("nothing to find here", "zebra")).toBe("nothing to find here")
  })

  it("handles an empty body", () => {
    expect(applySearchTerm("", "memory")).toBe("")
  })

  it("marks a term adjacent to punctuation and at the string edges", () => {
    const out = applySearchTerm("memory, then memory", "memory")
    expect(out.match(/<mark/g)).toHaveLength(2)
    expect(out.startsWith("<mark")).toBe(true)
    expect(out.endsWith("</mark>")).toBe(true)
  })
})

describe("orderHitsByDocument", () => {
  // The order this endpoint actually returned on one document, measured.
  const order = new Map([
    ["s20", 20], ["s14", 14], ["s10", 10], ["s11", 11], ["s25", 25],
  ])

  it("puts relevance-ranked hits back into reading order", () => {
    const hits = [
      { section_id: "s20" }, { section_id: "s14" }, { section_id: "s10" },
      { section_id: "s11" }, { section_id: "s25" },
    ]
    expect(orderHitsByDocument(hits, order).map((h) => h.section_id)).toEqual([
      "s10", "s11", "s14", "s20", "s25",
    ])
  })

  it("keeps a hit whose section is not in the order map, sorted last", () => {
    const hits = [{ section_id: "unknown" }, { section_id: "s14" }]
    expect(orderHitsByDocument(hits, order).map((h) => h.section_id)).toEqual([
      "s14", "unknown",
    ])
  })

  it("does not mutate the input array", () => {
    const hits = [{ section_id: "s25" }, { section_id: "s10" }]
    orderHitsByDocument(hits, order)
    expect(hits.map((h) => h.section_id)).toEqual(["s25", "s10"])
  })

  it("handles an empty hit list", () => {
    expect(orderHitsByDocument([], order)).toEqual([])
  })
})

describe("widenedListLimit", () => {
  const PAGE = 40
  const MAX = 200

  it("leaves the window alone when the target is already rendered", () => {
    expect(widenedListLimit(40, 12, PAGE, MAX)).toBe(40)
    expect(widenedListLimit(40, 39, PAGE, MAX)).toBe(40)
  })

  it("widens to the page boundary covering the target", () => {
    // index 40 is the 41st section -- one past a 40-section window.
    expect(widenedListLimit(40, 40, PAGE, MAX)).toBe(80)
    expect(widenedListLimit(40, 95, PAGE, MAX)).toBe(120)
  })

  it("never shrinks an already-wider window", () => {
    expect(widenedListLimit(160, 45, PAGE, MAX)).toBe(160)
  })

  it("clamps at the server's maximum window", () => {
    // The server refuses a larger window; asking for more would 422.
    expect(widenedListLimit(40, 900, PAGE, MAX)).toBe(MAX)
  })

  it("ignores a target that is not in the document", () => {
    expect(widenedListLimit(40, -1, PAGE, MAX)).toBe(40)
  })
})
