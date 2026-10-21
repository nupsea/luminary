import { describe, expect, it } from "vitest"

import { chipCount, toggleChip, visibleChips, type TypeChip } from "./filterChips"
import type { DocumentKind } from "./types"

const BOOKS: TypeChip = { id: "book", label: "Books" }
const TECHNICAL: TypeChip = { id: "technical", label: "Technical" }
const VIDEO: TypeChip = { id: "video", label: "Video" }

const FACETS = {
  kinds: { book: 17, technical: 24, audio: 4 },
  formats: { pdf: 18, epub: 1 },
  total: 45,
  favorite_count: 5,
}

describe("visibleChips", () => {
  it("drops a chip nothing in the library can match", () => {
    const shown = visibleChips([BOOKS, TECHNICAL, VIDEO], FACETS).map((v) => v.chip.id)
    expect(shown).toEqual(["book", "technical"])
  })

  it("shows nothing at all before the counts arrive", () => {
    // Rather than flashing every chip in and then removing most of them.
    expect(visibleChips([BOOKS, TECHNICAL], undefined)).toEqual([])
  })

  it("counts a chip from the server's kind counts", () => {
    expect(chipCount(TECHNICAL, FACETS)).toBe(24)
    expect(chipCount(VIDEO, FACETS)).toBe(0)
  })
})

describe("toggleChip", () => {
  it("adds and removes its kind", () => {
    const on = toggleChip(TECHNICAL, new Set<DocumentKind>())
    expect([...on]).toEqual(["technical"])
    expect(toggleChip(TECHNICAL, on).size).toBe(0)
  })

  it("leaves other selections alone", () => {
    const next = toggleChip(BOOKS, new Set<DocumentKind>(["audio"]))
    expect([...next].sort()).toEqual(["audio", "book"])
  })
})
