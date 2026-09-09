/**
 * What the Practice face can run right now.
 *
 * The due rule has to match `GET /study/due`, which filters `due_date <= now`
 * in SQL: a card with no due date is not due there, so it must not be counted
 * due here either. Counting it would put a card in the panel's summary that the
 * run it starts cannot contain.
 */

import type { Flashcard, MaterialHeadroom } from "@/lib/studyApi"

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


/**
 * Whether this scope has anything left to write questions from.
 *
 * The panel asks before offering to add more, because a deck that already
 * covers its material yields nothing: generation reads a passage the deck holds
 * and the near-duplicate filter removes every question it produces. The learner
 * saw a button, a wait, and then a red error.
 *
 * Three cases are deliberately NOT exhausted, because each would hide a control
 * that works:
 *
 *  - `null`: the ask failed. An unanswered question is not a no.
 *  - no chunks at all: the document is unreadable, not covered, and "every
 *    passage already has a question" would be a lie about an empty document.
 *  - cards that name no passage: they claim nothing, so the unused count is an
 *    upper bound the deck may already have eaten into. It can over-state what
 *    is left, which keeps the button — the safe direction — and never hides one.
 */
export function materialExhausted(headroom: MaterialHeadroom | null | undefined): boolean {
  if (!headroom) return false
  if (headroom.total_chunks === 0) return false
  return headroom.unused_chunks === 0
}

/** What to say when a generation call comes back with no cards.
 *
 * It used to say "There may be no unused material left here" whatever the
 * reason, on a document with 37 of its 40 passages untouched. An empty result
 * means nothing the model wrote survived the checks -- the grounding gate
 * refuses a card whose quote is not verbatim in the passage, which a transcript
 * makes easy to fail -- and that is worth retrying. Saying the material is spent
 * when it is not sends the learner away from a deck that still has cards in it.
 */
export function noCardsNote(headroom: MaterialHeadroom | null | undefined): string {
  if (materialExhausted(headroom)) {
    return "No cards came back. Every passage here already has a question on it."
  }
  const left =
    headroom && headroom.total_chunks > 0
      ? ` ${headroom.unused_chunks} of ${headroom.total_chunks} passages here still have no card,`
      : ""
  return (
    "No cards came back. Nothing the model wrote this time held up against the" +
    ` document --${left} so another go may work.`
  )
}

/** What the button that moves a run on should say.
 *
 * It said "Next card" on the last card of the queue, and on a card pulled back
 * out of the summary -- both of which land on the readout rather than another
 * question. A button names where it goes.
 */
export function advanceLabel(opts: {
  fromSummary: boolean
  index: number
  queueLength: number
}): string {
  if (opts.fromSummary) return "Back to results"
  return opts.index + 1 >= opts.queueLength ? "Finish" : "Next card"
}
