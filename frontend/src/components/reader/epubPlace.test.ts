import { describe, expect, it } from "vitest"
import { blockAtLine, epubPlaceOf, samePlace } from "./epubPlace"

describe("epubPlaceOf", () => {
  it("is no place without a chapter, and a chapter's start without a block", () => {
    expect(epubPlaceOf(null, 12)).toBeNull()
    expect(epubPlaceOf(4, null)).toEqual({ chapter: 4, block: 0 })
    expect(epubPlaceOf(0, 12)).toEqual({ chapter: 0, block: 12 })
  })
})

describe("blockAtLine", () => {
  const tops = [0, 40, 40, 120, 300]
  const topOf = (i: number) => tops[i]

  it("is the last block whose top has reached the reading line", () => {
    expect(blockAtLine(tops.length, topOf, 100)).toBe(2)
    expect(blockAtLine(tops.length, topOf, 120)).toBe(3)
    expect(blockAtLine(tops.length, topOf, 1000)).toBe(4)
  })

  it("prefers the innermost of blocks that start together, so a restore lands where it was saved", () => {
    // An <li> and the <p> inside it share a top.
    expect(blockAtLine(tops.length, topOf, 40)).toBe(2)
  })

  it("is the first block above the start of a chapter, and 0 for an empty one", () => {
    expect(blockAtLine(tops.length, (i) => tops[i] + 50, 10)).toBe(0)
    expect(blockAtLine(0, topOf, 10)).toBe(0)
  })
})

describe("samePlace", () => {
  it("needs both chapter and block to match", () => {
    expect(samePlace({ chapter: 3, block: 7 }, { chapter: 3, block: 7 })).toBe(true)
    expect(samePlace({ chapter: 3, block: 7 }, { chapter: 3, block: 8 })).toBe(false)
    expect(samePlace({ chapter: 3, block: 7 }, { chapter: 4, block: 7 })).toBe(false)
    expect(samePlace(null, { chapter: 3, block: 7 })).toBe(false)
  })
})
