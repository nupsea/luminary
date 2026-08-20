import { describe, expect, it } from "vitest"

import { chipCount, chipIsActive, toggleChip, visibleChips, type TypeChip } from "./filterChips"
import type { ContentType } from "./types"

const BOOKS: TypeChip = { id: "book", label: "Books", types: ["book"] }
const TECHNICAL: TypeChip = {
  id: "technical",
  label: "Technical",
  types: ["tech_book", "tech_article"],
}
const VIDEO: TypeChip = { id: "video", label: "Video", types: ["video"] }

const FACETS = {
  content_types: { book: 17, tech_book: 8, tech_article: 16, audio: 4 },
  formats: { pdf: 18, epub: 1 },
  total: 45,
}

describe("visibleChips", () => {
  it("drops a chip nothing in the library can match", () => {
    // The reported problem: five of ten chips filtered for values no document
    // could hold -- `code` is not in the backend's ContentType union at all.
    const shown = visibleChips([BOOKS, TECHNICAL, VIDEO], FACETS).map((v) => v.chip.id)
    expect(shown).toEqual(["book", "technical"])
  })

  it("shows nothing at all before the counts arrive", () => {
    // Rather than flashing every chip in and then removing most of them.
    expect(visibleChips([BOOKS, TECHNICAL], undefined)).toEqual([])
  })

  it("counts a folded chip as the sum of what it stands for", () => {
    expect(chipCount(TECHNICAL, FACETS)).toBe(24)
    expect(chipCount(BOOKS, FACETS)).toBe(17)
  })
})

describe("toggleChip", () => {
  it("moves both halves of a folded chip together", () => {
    const on = toggleChip(TECHNICAL, new Set<ContentType>())
    expect([...on].sort()).toEqual(["tech_article", "tech_book"])
    expect(toggleChip(TECHNICAL, on).size).toBe(0)
  })

  it("is not on while only one half is selected", () => {
    // Otherwise clicking Technical with tech_book already set would clear it
    // and leave the chip looking untouched.
    const half = new Set<ContentType>(["tech_book"])
    expect(chipIsActive(TECHNICAL, half)).toBe(false)
    expect([...toggleChip(TECHNICAL, half)].sort()).toEqual(["tech_article", "tech_book"])
  })

  it("leaves other selections alone", () => {
    const next = toggleChip(BOOKS, new Set<ContentType>(["audio"]))
    expect([...next].sort()).toEqual(["audio", "book"])
  })
})
