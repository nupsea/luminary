import { describe, expect, it } from "vitest"

import type { Flashcard } from "@/lib/studyApi"
import { advanceLabel, materialExhausted, noCardsNote, summariseDeck } from "./practiceDeck"

function card(id: string, due: string | null): Flashcard {
  return {
    id,
    question: "q",
    answer: "a",
    source_excerpt: "",
    due_date: due,
    section_id: null,
    flashcard_type: null,
    cloze_text: null,
    fsrs_stability: 0,
    reps: 0,
  }
}

const NOW = Date.parse("2026-09-08T12:00:00Z")

describe("summariseDeck", () => {
  it("counts a card due in the past and one due exactly now", () => {
    const deck = [
      card("past", "2026-09-01T00:00:00Z"),
      card("now", "2026-09-08T12:00:00Z"),
    ]
    expect(summariseDeck(deck, NOW).due.map((c) => c.id)).toEqual(["past", "now"])
  })

  it("leaves a card scheduled ahead out of the due set", () => {
    const deck = [card("later", "2026-09-20T00:00:00Z")]
    const s = summariseDeck(deck, NOW)
    expect(s.total).toBe(1)
    expect(s.due).toEqual([])
  })

  it("never counts a card with no due date, the way the due query does not", () => {
    // GET /study/due filters `due_date <= now` in SQL, which drops NULL. A panel
    // that called this card due would promise a run the backend cannot fill.
    expect(summariseDeck([card("undated", null)], NOW).due).toEqual([])
  })

  it("reports an empty deck without inventing a due count", () => {
    expect(summariseDeck([], NOW)).toEqual({ total: 0, due: [] })
  })
})

describe("materialExhausted", () => {
  const base = {
    total_chunks: 26,
    used_chunks: 8,
    unused_chunks: 18,
    cards: 6,
    cards_without_sources: 0,
  }

  it("is false while passages remain unread", () => {
    expect(materialExhausted(base)).toBe(false)
  })

  it("is true once every passage has a question", () => {
    expect(materialExhausted({ ...base, used_chunks: 26, unused_chunks: 0 })).toBe(true)
  })

  it("is false when the ask failed -- an unanswered question is not a no", () => {
    expect(materialExhausted(null)).toBe(false)
    expect(materialExhausted(undefined)).toBe(false)
  })

  it("is false for a document with no chunks at all", () => {
    // Unreadable, not covered. "Every passage already has a question" would be
    // a lie about a document that has none.
    expect(
      materialExhausted({ ...base, total_chunks: 0, used_chunks: 0, unused_chunks: 0 }),
    ).toBe(false)
  })

  it("still reports exhausted when some cards name no passage", () => {
    // Those cards claim nothing, so unused_chunks is an upper bound. Zero of an
    // upper bound is still zero.
    expect(
      materialExhausted({
        ...base,
        used_chunks: 26,
        unused_chunks: 0,
        cards_without_sources: 4,
      }),
    ).toBe(true)
  })
})

describe("noCardsNote", () => {
  it("does not blame exhausted material when 37 of 40 passages are untouched", () => {
    // The reported case: three cards on a 40-chunk transcript, "add more"
    // returned nothing, and the panel said the material may be spent.
    const note = noCardsNote({
      total_chunks: 40,
      used_chunks: 3,
      unused_chunks: 37,
      cards: 3,
      cards_without_sources: 0,
    })
    expect(note).not.toMatch(/no unused material/i)
    expect(note).toContain("37 of 40")
    expect(note).toMatch(/another go/i)
  })

  it("says the material is spent only when it is", () => {
    const note = noCardsNote({
      total_chunks: 12,
      used_chunks: 12,
      unused_chunks: 0,
      cards: 9,
      cards_without_sources: 0,
    })
    expect(note).toMatch(/already has a question/i)
  })

  it("makes no claim about the material when the headroom is unknown", () => {
    const note = noCardsNote(null)
    expect(note).toContain("No cards came back")
    expect(note).not.toMatch(/passages here/i)
  })
})

describe("advanceLabel", () => {
  it("says Finish on the last card of the run", () => {
    expect(advanceLabel({ fromSummary: false, index: 2, queueLength: 3 })).toBe("Finish")
  })

  it("says Next card while questions remain", () => {
    expect(advanceLabel({ fromSummary: false, index: 0, queueLength: 3 })).toBe("Next card")
    expect(advanceLabel({ fromSummary: false, index: 1, queueLength: 3 })).toBe("Next card")
  })

  it("returns to the summary for a card answered again from it", () => {
    // Not a position in the queue: advancing from it goes back to the readout
    // however many cards are left.
    expect(advanceLabel({ fromSummary: true, index: 0, queueLength: 9 })).toBe(
      "Back to results",
    )
  })

  it("says Finish on a one-card run", () => {
    expect(advanceLabel({ fromSummary: false, index: 0, queueLength: 1 })).toBe("Finish")
  })
})
