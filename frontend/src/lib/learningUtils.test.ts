import { describe, it, expect } from "vitest"
import {
  buildStatPillNavigateDetail,
  computeAvgMastery,
  getMostRecentDocument,
  STAT_PILL_LABELS,
} from "./learningUtils"

describe("buildStatPillNavigateDetail", () => {
  it("returns correct tab for study pill", () => {
    const detail = buildStatPillNavigateDetail("study")
    expect(detail.tab).toBe("study")
  })

  it("returns correct tab for notes pill", () => {
    const detail = buildStatPillNavigateDetail("notes")
    expect(detail.tab).toBe("notes")
  })

  it("returns correct tab for progress pill", () => {
    const detail = buildStatPillNavigateDetail("progress")
    expect(detail.tab).toBe("progress")
  })
})

describe("STAT_PILL_LABELS", () => {
  it("has correct label for books", () => {
    expect(STAT_PILL_LABELS.books).toBe("books")
  })

  it("has correct label for notes", () => {
    expect(STAT_PILL_LABELS.notes).toBe("notes")
  })

  it("has correct label for mastery", () => {
    expect(STAT_PILL_LABELS.mastery).toBe("avg mastery")
  })

  it("has correct label for due", () => {
    expect(STAT_PILL_LABELS.due).toBe("cards due")
  })
})

describe("computeAvgMastery", () => {
  it("returns null for empty array", () => {
    expect(computeAvgMastery([])).toBeNull()
  })

  it("returns null for all-null array", () => {
    expect(computeAvgMastery([null, null])).toBeNull()
  })

  it("returns correct average for single value", () => {
    expect(computeAvgMastery([80])).toBe(80)
  })

  it("returns rounded average for multiple values", () => {
    // (70 + 90) / 2 = 80
    expect(computeAvgMastery([70, 90])).toBe(80)
  })

  it("rounds fractional averages", () => {
    // (70 + 71) / 2 = 70.5 -> rounded to 71
    expect(computeAvgMastery([70, 71])).toBe(71)
  })

  it("skips null values in mixed array", () => {
    // only 80 and 100 are valid; avg = 90
    expect(computeAvgMastery([80, null, 100])).toBe(90)
  })
})

describe("getMostRecentDocument", () => {
  it("returns null for empty array", () => {
    expect(getMostRecentDocument([])).toBeNull()
  })

  it("returns the first item from a pre-sorted list (most recently viewed)", () => {
    const items = [
      { id: "doc-1", title: "Most Recent" },
      { id: "doc-2", title: "Older" },
    ]
    const result = getMostRecentDocument(items)
    expect(result).not.toBeNull()
    expect(result?.id).toBe("doc-1")
  })

  it("returns the single item when list has one element", () => {
    const items = [{ id: "doc-only", title: "Only Doc" }]
    expect(getMostRecentDocument(items)?.id).toBe("doc-only")
  })
})
