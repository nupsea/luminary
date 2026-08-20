import { describe, expect, it } from "vitest"
import { activeMatchIndexForPage, buildGlobalMatches, findMatchIndices, formatMatchCounts, printedPageLabel } from "./pdfSearchUtils"

describe("findMatchIndices", () => {
  it("returns empty for empty query", () => {
    expect(findMatchIndices("hello world", "")).toEqual([])
  })

  it("finds single occurrence", () => {
    expect(findMatchIndices("hello world", "world")).toEqual([6])
  })

  it("finds multiple occurrences", () => {
    expect(findMatchIndices("abcabc", "abc")).toEqual([0, 3])
  })

  it("is case-insensitive", () => {
    expect(findMatchIndices("Hello HELLO hello", "hello")).toEqual([0, 6, 12])
  })

  it("handles overlapping potential matches", () => {
    expect(findMatchIndices("aaa", "aa")).toEqual([0, 1])
  })

  it("returns empty when no match", () => {
    expect(findMatchIndices("hello world", "xyz")).toEqual([])
  })
})

describe("buildGlobalMatches", () => {
  it("returns empty for empty query", () => {
    const cache = new Map([[1, "hello"], [2, "world"]])
    expect(buildGlobalMatches(cache, "")).toEqual([])
  })

  it("builds matches across pages in page order", () => {
    const cache = new Map([
      [3, "page three has the word"],
      [1, "page one has the word twice word"],
      [2, "nothing here"],
    ])
    const matches = buildGlobalMatches(cache, "word")
    // "page one has the word twice word" -> indices 18, 30? Let's check:
    // p-a-g-e- -o-n-e- -h-a-s- -t-h-e- -w-o-r-d = index 17 for "word"
    // ...twice word -> "word" at index 28
    // "page three has the word" -> index 19
    expect(matches).toEqual([
      { page: 1, index: 17 },
      { page: 1, index: 28 },
      { page: 3, index: 19 },
    ])
  })

  it("returns empty when no pages match", () => {
    const cache = new Map([[1, "hello"]])
    expect(buildGlobalMatches(cache, "xyz")).toEqual([])
  })
})

describe("formatMatchCounts", () => {
  const matches = [
    { page: 1, index: 0 },
    { page: 1, index: 10 },
    { page: 2, index: 5 },
    { page: 3, index: 0 },
    { page: 3, index: 8 },
    { page: 3, index: 20 },
  ]

  it("shows 'No matches' when empty", () => {
    const result = formatMatchCounts([], -1, 1)
    expect(result.label).toBe("No matches")
    expect(result.totalCount).toBe(0)
  })

  it("shows page and total counts for active match on current page", () => {
    const result = formatMatchCounts(matches, 0, 1)
    expect(result.pageCount).toBe(2)
    expect(result.totalCount).toBe(6)
    expect(result.pageIndex).toBe(0)
    expect(result.label).toBe("1 of 2 on page, 6 total")
  })

  it("shows second match on page", () => {
    const result = formatMatchCounts(matches, 1, 1)
    expect(result.pageIndex).toBe(1)
    expect(result.label).toBe("2 of 2 on page, 6 total")
  })

  it("shows page count without index when active match is on different page", () => {
    // Active match is on page 2, but we're viewing page 1
    const result = formatMatchCounts(matches, 2, 1)
    expect(result.pageIndex).toBe(-1)
    expect(result.label).toBe("2 on page, 6 total")
  })

  it("handles page with no matches", () => {
    const result = formatMatchCounts(matches, 0, 5)
    expect(result.pageCount).toBe(0)
    expect(result.label).toBe("0 on page, 6 total")
  })
})

describe("activeMatchIndexForPage", () => {
  const matches = [
    { page: 1, index: 10 },
    { page: 2, index: 5 },
    { page: 2, index: 40 },
    { page: 3, index: 7 },
  ]

  it("finds the active match's position among that page's matches", () => {
    expect(activeMatchIndexForPage(matches, 2, 2)).toBe(1)
  })

  it("reports -1 when the active match is on another page", () => {
    expect(activeMatchIndexForPage(matches, 0, 2)).toBe(-1)
  })

  it("reports -1 when nothing is active", () => {
    expect(activeMatchIndexForPage(matches, -1, 1)).toBe(-1)
  })

  it("is stable while later pages are still being extracted", () => {
    // The flicker case: extraction appends matches from further into the book
    // once per batch. The current page's answer must not change, or the effect
    // re-runs and clears every overlay before redrawing the same thing.
    const grown = [...matches, { page: 9, index: 1 }, { page: 12, index: 3 }]
    expect(activeMatchIndexForPage(grown, 2, 2)).toBe(activeMatchIndexForPage(matches, 2, 2))
  })
})

describe("printedPageLabel", () => {
  // Sheet positions and their printed labels, measured on a real 613-page book.
  const labels = ["Cover", "BackCover", "i", "ii", "iii", "iv"]

  it("reports the printed label when it differs from the sheet number", () => {
    expect(printedPageLabel(labels, 6)).toBe("iv")
    expect(printedPageLabel(labels, 1)).toBe("Cover")
  })

  it("reports nothing when the PDF defines no labels", () => {
    // Three of four books in one library define none; their footers are right
    // as they are and must not grow a redundant second number.
    expect(printedPageLabel(null, 5)).toBeNull()
    expect(printedPageLabel([], 5)).toBeNull()
  })

  it("reports nothing when the label is just the sheet number", () => {
    expect(printedPageLabel(["1", "2", "3"], 2)).toBeNull()
  })

  it("reports nothing outside the document", () => {
    expect(printedPageLabel(labels, 0)).toBeNull()
    expect(printedPageLabel(labels, 99)).toBeNull()
  })
})
