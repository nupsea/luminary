// What the review screen is entitled to say about a card's quote.
//
// Two orthogonal checks. `grounding` proves the excerpt is a real span of the
// document; `factuality` proves the answer follows from it. A card can pass the
// first and fail the second -- a genuine sentence quoted under an answer the
// passage does not support -- and that is the case worth surfacing, because
// `grounding` alone reads clean on exactly those cards.
//
// Silence is a claim too: the panel prints the excerpt under a heading that says
// "Source", so an unchecked card says it is unchecked rather than saying nothing.

export interface SourceNote {
  text: string
  className: string
}

const MUTED = "text-muted-foreground"
const GOOD = "text-emerald-700 dark:text-emerald-400"
const DOUBT = "text-amber-700 dark:text-amber-400"

export const SOURCE_NOTES: Record<string, SourceNote> = {
  checked: { text: "Found in this document, and the answer follows from it", className: GOOD },
  verified: { text: "Found in this document", className: GOOD },
  answer_unsupported: {
    text: "The answer does not follow from this passage -- treat it as unverified",
    className: DOUBT,
  },
  unsupported: {
    text: "Not found in this document -- treat this quote as unverified",
    className: DOUBT,
  },
  unverifiable: { text: "Could not be checked against a document", className: MUTED },
  unchecked: { text: "Not checked against the document yet", className: MUTED },
}

export interface CardChecks {
  grounding?: string
  factuality?: string
}

/** The weaker of the two claims, so the card never over-states what was verified. */
export function sourceNote(card: CardChecks): SourceNote {
  if (card.factuality === "unsupported") return SOURCE_NOTES.answer_unsupported
  if (card.grounding === "unsupported") return SOURCE_NOTES.unsupported
  if (card.grounding === "verified" && card.factuality === "supported")
    return SOURCE_NOTES.checked
  return SOURCE_NOTES[card.grounding ?? "unchecked"] ?? SOURCE_NOTES.unchecked
}

/** Whether the panel should visibly doubt the excerpt it is about to print. */
export function isDoubted(card: CardChecks): boolean {
  return card.grounding === "unsupported" || card.factuality === "unsupported"
}
