import { describe, it, expect } from "vitest"

import {
  applySearchTerm,
  extendWindowDown,
  extendWindowUp,
  orderHitsByDocument,
  SEARCH_MARK_CLASS,
  setActiveSearchMark,
  windowIncluding,
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

  it("falls back to highlighting individual keywords when full multi-word term is not present verbatim", () => {
    const out = applySearchTerm("We use HNSW for nearest-neighbor search", "HNSW (Hierarchical Navigable Small World)")
    expect(out).toContain(`<mark class="${SEARCH_MARK_CLASS}">HNSW</mark>`)
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

describe("windowIncluding", () => {
  const PAGE = 40
  const MAX = 200
  const top = (limit: number) => ({ start: 0, limit })
  const contains = (w: { start: number; limit: number }, i: number) =>
    i >= w.start && i < w.start + w.limit

  it("leaves the window alone when the target is already rendered", () => {
    expect(windowIncluding(top(40), 12, PAGE, MAX)).toEqual(top(40))
    expect(windowIncluding(top(40), 39, PAGE, MAX)).toEqual(top(40))
  })

  it("widens to the page boundary covering the target", () => {
    // index 40 is the 41st section -- one past a 40-section window.
    expect(windowIncluding(top(40), 40, PAGE, MAX)).toEqual(top(80))
    expect(windowIncluding(top(40), 95, PAGE, MAX)).toEqual(top(120))
  })

  it("never shrinks an already-wider window", () => {
    expect(windowIncluding(top(160), 45, PAGE, MAX)).toEqual(top(160))
  })

  it("moves to a target past the server's maximum window, and holds it", () => {
    // Growing from 0 capped at 200 and never reached section 226 of 448 (AI
    // Engineering), so its citations opened the book at the first page.
    for (const target of [200, 226, 900]) {
      const w = windowIncluding(top(40), target, PAGE, MAX)
      expect(contains(w, target)).toBe(true)
      expect(w.limit).toBeLessThanOrEqual(MAX)
    }
    expect(windowIncluding(top(40), 226, PAGE, MAX)).toEqual({ start: 160, limit: 106 })
  })

  it("moves back to a target above a moved window", () => {
    const w = windowIncluding({ start: 400, limit: 80 }, 10, PAGE, MAX)
    expect(contains(w, 10)).toBe(true)
    expect(w.start).toBe(0)
  })

  it("ignores a target that is not in the document", () => {
    expect(windowIncluding(top(40), -1, PAGE, MAX)).toEqual(top(40))
  })
})

describe("extendWindowDown / extendWindowUp", () => {
  const PAGE = 40
  const MAX = 200

  it("grows down to the maximum, then slides", () => {
    expect(extendWindowDown({ start: 0, limit: 40 }, PAGE, MAX)).toEqual({ start: 0, limit: 80 })
    expect(extendWindowDown({ start: 0, limit: 200 }, PAGE, MAX)).toEqual({ start: 40, limit: 200 })
  })

  it("grows up to section 0, trimming the tail at the maximum", () => {
    expect(extendWindowUp({ start: 160, limit: 106 }, PAGE, MAX)).toEqual({ start: 120, limit: 146 })
    expect(extendWindowUp({ start: 40, limit: 200 }, PAGE, MAX)).toEqual({ start: 0, limit: 200 })
    expect(extendWindowUp({ start: 20, limit: 40 }, PAGE, MAX)).toEqual({ start: 0, limit: 60 })
  })
})

describe("setActiveSearchMark", () => {
  it("returns zeros when no marks are found", () => {
    const container = {
      querySelectorAll: () => [],
    } as unknown as HTMLElement
    const res = setActiveSearchMark(container, 0)
    expect(res.total).toBe(0)
    expect(res.activeEl).toBeNull()
    expect(res.sectionId).toBeNull()
  })

  it("adds active classes to target index and removes from others", () => {
    const classSet1 = new Set(["bg-sky-200"])
    const classSet2 = new Set(["bg-sky-200"])
    const mark1 = {
      classList: {
        add: (...cls: string[]) => cls.forEach((c) => classSet1.add(c)),
        remove: (...cls: string[]) => cls.forEach((c) => classSet1.delete(c)),
      },
      closest: () => ({ id: "read-sec-alpha" }),
    } as unknown as HTMLElement
    const mark2 = {
      classList: {
        add: (...cls: string[]) => cls.forEach((c) => classSet2.add(c)),
        remove: (...cls: string[]) => cls.forEach((c) => classSet2.delete(c)),
      },
      closest: () => ({ id: "read-sec-beta" }),
    } as unknown as HTMLElement

    const container = {
      querySelectorAll: () => [mark1, mark2],
    } as unknown as HTMLElement

    const res = setActiveSearchMark(container, 1)
    expect(res.total).toBe(2)
    expect(res.activeEl).toBe(mark2)
    expect(res.sectionId).toBe("beta")
    expect(classSet2.has("ring-amber-500")).toBe(true)
    expect(classSet1.has("ring-amber-500")).toBe(false)
  })
})

