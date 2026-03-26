import { describe, expect, it } from "vitest"
import {
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
