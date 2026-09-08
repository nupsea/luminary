import { describe, expect, it } from "vitest"

import type { Flashcard } from "@/lib/studyApi"
import { summariseDeck } from "./practiceDeck"

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
