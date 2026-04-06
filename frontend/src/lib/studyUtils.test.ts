import { describe, expect, it } from "vitest"
import {
  BLOOM_LEVEL_LABELS,
  FSRS_STATE_LABELS,
  INSIGHTS_SECTIONS,
  buildSearchParams,
  buildSmartGenerateParams,
  computeMasteryPct,
  getDeckDisplayName,
  selectSmartMode,
} from "./studyUtils"

// ---------------------------------------------------------------------------
// selectSmartMode
// ---------------------------------------------------------------------------

describe("selectSmartMode", () => {
  it("returns basic when mastery is 0%", () => {
    expect(selectSmartMode(0)).toBe("basic")
  })

  it("returns basic just below 30% threshold", () => {
    expect(selectSmartMode(29.9)).toBe("basic")
  })

  it("returns feynman at exactly 30%", () => {
    expect(selectSmartMode(30)).toBe("feynman")
  })

  it("returns feynman at 50%", () => {
    expect(selectSmartMode(50)).toBe("feynman")
  })

  it("returns feynman just below 70% threshold", () => {
    expect(selectSmartMode(69.9)).toBe("feynman")
  })

  it("returns cloze at exactly 70%", () => {
    expect(selectSmartMode(70)).toBe("cloze")
  })

  it("returns cloze at 100%", () => {
    expect(selectSmartMode(100)).toBe("cloze")
  })
})

// ---------------------------------------------------------------------------
// computeMasteryPct
// ---------------------------------------------------------------------------

describe("computeMasteryPct", () => {
  it("returns 0 for empty card list", () => {
    expect(computeMasteryPct([])).toBe(0)
  })

  it("returns 0 when no cards are in review state", () => {
    const cards = [
      { fsrs_state: "new" },
      { fsrs_state: "learning" },
      { fsrs_state: "relearning" },
    ]
    expect(computeMasteryPct(cards)).toBe(0)
  })

  it("returns 100 when all cards are in review state", () => {
    const cards = [{ fsrs_state: "review" }, { fsrs_state: "review" }]
    expect(computeMasteryPct(cards)).toBe(100)
  })

  it("returns 50 when half the cards are in review state", () => {
    const cards = [
      { fsrs_state: "new" },
      { fsrs_state: "learning" },
      { fsrs_state: "review" },
      { fsrs_state: "review" },
    ]
    expect(computeMasteryPct(cards)).toBe(50)
  })

  it("computes mastery pct correctly with mixed states", () => {
    const cards = [
      { fsrs_state: "review" },
      { fsrs_state: "new" },
      { fsrs_state: "new" },
      { fsrs_state: "new" },
    ]
    // 1 out of 4 = 25%
    expect(computeMasteryPct(cards)).toBe(25)
  })
})

// ---------------------------------------------------------------------------
// getDeckDisplayName
// ---------------------------------------------------------------------------

describe("getDeckDisplayName", () => {
  it("returns deck name unchanged when it is not 'default'", () => {
    expect(
      getDeckDisplayName({
        deckName: "My Custom Deck",
        documentId: "doc1",
        docTitle: "The Time Machine",
        isOnlyDeckForDocument: true,
      }),
    ).toBe("My Custom Deck")
  })

  it("aliases 'default' to document title when it is the only deck for the document", () => {
    expect(
      getDeckDisplayName({
        deckName: "default",
        documentId: "doc1",
        docTitle: "The Time Machine",
        isOnlyDeckForDocument: true,
      }),
    ).toBe("The Time Machine")
  })

  it("returns 'default' when there are multiple decks for the document", () => {
    expect(
      getDeckDisplayName({
        deckName: "default",
        documentId: "doc1",
        docTitle: "The Time Machine",
        isOnlyDeckForDocument: false,
      }),
    ).toBe("default")
  })

  it("returns 'default' when documentId is null", () => {
    expect(
      getDeckDisplayName({
        deckName: "default",
        documentId: null,
        docTitle: "Some Title",
        isOnlyDeckForDocument: true,
      }),
    ).toBe("default")
  })

  it("returns 'default' when docTitle is undefined and it is the only deck", () => {
    expect(
      getDeckDisplayName({
        deckName: "default",
        documentId: "doc1",
        docTitle: undefined,
        isOnlyDeckForDocument: true,
      }),
    ).toBe("default")
  })
})

// ---------------------------------------------------------------------------
// S185: buildSmartGenerateParams (AC8)
// ---------------------------------------------------------------------------

describe("buildSmartGenerateParams", () => {
  it("returns basic smart_mode when mastery < 30%", () => {
    const params = buildSmartGenerateParams(15, "doc-1")
    expect(params.smart_mode).toBe("basic")
    expect(params.document_id).toBe("doc-1")
    expect(params.scope).toBe("full")
    expect(params.section_heading).toBeNull()
    expect(params.count).toBe(10)
    expect(params.difficulty).toBe("medium")
  })

  it("returns feynman smart_mode when mastery is 30-69%", () => {
    const params = buildSmartGenerateParams(50, "doc-2")
    expect(params.smart_mode).toBe("feynman")
  })

  it("returns cloze smart_mode when mastery >= 70%", () => {
    const params = buildSmartGenerateParams(85, "doc-3")
    expect(params.smart_mode).toBe("cloze")
  })

  it("returns basic at 0% mastery", () => {
    expect(buildSmartGenerateParams(0, "doc-x").smart_mode).toBe("basic")
  })

  it("returns cloze at 100% mastery", () => {
    expect(buildSmartGenerateParams(100, "doc-x").smart_mode).toBe("cloze")
  })
})

// ---------------------------------------------------------------------------
// S185: INSIGHTS_SECTIONS (AC9)
// ---------------------------------------------------------------------------

describe("INSIGHTS_SECTIONS", () => {
  it("has exactly 3 sections: health_report, bloom_audit, struggling", () => {
    expect(INSIGHTS_SECTIONS).toHaveLength(3)
    expect(INSIGHTS_SECTIONS).toContain("health_report")
    expect(INSIGHTS_SECTIONS).toContain("bloom_audit")
    expect(INSIGHTS_SECTIONS).toContain("struggling")
  })
})

// ---------------------------------------------------------------------------
// S184: buildSearchParams
// ---------------------------------------------------------------------------

describe("buildSearchParams", () => {
  it("returns empty params when no filters are set", () => {
    const params = buildSearchParams({})
    expect(params.toString()).toBe("")
  })

  it("sets query param", () => {
    const params = buildSearchParams({ query: "recursion" })
    expect(params.get("query")).toBe("recursion")
  })

  it("sets multiple filters", () => {
    const params = buildSearchParams({
      query: "test",
      document_id: "doc-1",
      bloom_level_min: 3,
      fsrs_state: "new",
      page: 2,
    })
    expect(params.get("query")).toBe("test")
    expect(params.get("document_id")).toBe("doc-1")
    expect(params.get("bloom_level_min")).toBe("3")
    expect(params.get("fsrs_state")).toBe("new")
    expect(params.get("page")).toBe("2")
  })

  it("omits undefined and null-ish values", () => {
    const params = buildSearchParams({ query: "", document_id: undefined })
    expect(params.toString()).toBe("")
  })
})

// ---------------------------------------------------------------------------
// S184: Constants
// ---------------------------------------------------------------------------

describe("FSRS_STATE_LABELS", () => {
  it("has entries for all four FSRS states", () => {
    expect(Object.keys(FSRS_STATE_LABELS)).toEqual(
      expect.arrayContaining(["new", "learning", "review", "relearning"]),
    )
  })
})

describe("BLOOM_LEVEL_LABELS", () => {
  it("has entries for levels 1-6", () => {
    expect(Object.keys(BLOOM_LEVEL_LABELS).map(Number).sort()).toEqual([1, 2, 3, 4, 5, 6])
  })
})
