import { describe, expect, it } from "vitest"

import type { Flashcard } from "./studyApi"
import { topCards } from "./topCards"

const NOW = new Date("2026-10-28T12:00:00Z")

function card(id: string, extra: Partial<Flashcard> = {}): Flashcard {
  return {
    id,
    question: `${id}?`,
    answer: id,
    source_excerpt: id,
    due_date: "2026-10-28T09:00:00",
    section_id: "s1",
    flashcard_type: null,
    cloze_text: null,
    fsrs_stability: 0,
    reps: 0,
    ...extra,
  }
}

describe("topCards", () => {
  it("takes due cards before ones not yet due, then the weakest", () => {
    const picked = topCards(
      [
        card("later", { due_date: "2026-11-02T09:00:00", fsrs_stability: 0 }),
        card("strong", { fsrs_stability: 9 }),
        card("weak", { fsrs_stability: 1 }),
      ],
      2,
      NOW,
    )
    expect(picked.map((c) => c.id)).toEqual(["weak", "strong"])
  })

  it("reads a naive timestamp as UTC, not local time", () => {
    // Three hours ahead of NOW in UTC; due already only if read in a zone east of UTC+3.
    const picked = topCards(
      [card("future", { due_date: "2026-10-28T15:00:00" }), card("due")],
      1,
      NOW,
    )
    expect(picked.map((c) => c.id)).toEqual(["due"])
  })

  it("never picks a card whose quote or answer failed its check", () => {
    const picked = topCards(
      [
        card("bad-quote", { grounding: "unsupported" }),
        card("bad-answer", { factuality: "unsupported" }),
        card("ok", { grounding: "verified", fsrs_stability: 5 }),
      ],
      3,
      NOW,
    )
    expect(picked.map((c) => c.id)).toEqual(["ok"])
  })

  it("returns fewer than asked when the chapter has fewer", () => {
    expect(topCards([card("only")], 3, NOW)).toHaveLength(1)
  })
})
