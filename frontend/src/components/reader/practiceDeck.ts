/**
 * What the Practice face can run right now.
 *
 * The due rule has to match `GET /study/due`, which filters `due_date <= now`
 * in SQL: a card with no due date is not due there, so it must not be counted
 * due here either. Counting it would put a card in the panel's summary that the
 * run it starts cannot contain.
 */

import type { Flashcard } from "@/lib/studyApi"

export interface DeckSummary {
  total: number
  due: Flashcard[]
}

export function summariseDeck(cards: Flashcard[], now: number = Date.now()): DeckSummary {
  return {
    total: cards.length,
    due: cards.filter(
      (c) => c.due_date !== null && new Date(c.due_date).getTime() <= now,
    ),
  }
}
