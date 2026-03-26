/**
 * Pure utility functions for Study tab logic.
 * No React/store imports -- safe for Vitest node environment.
 */

export type SmartMode = "basic" | "feynman" | "cloze"

/**
 * Select the best flashcard generation mode based on mastery percentage.
 *
 * < 30%  mastered -> basic   (foundation building)
 * 30-69% mastered -> feynman (deeper comprehension via entity relationships)
 * >= 70% mastered -> cloze   (retrieval practice)
 */
export function selectSmartMode(masteryPct: number): SmartMode {
  if (masteryPct < 30) return "basic"
  if (masteryPct < 70) return "feynman"
  return "cloze"
}

/**
 * Compute mastery percentage from a card array.
 * Cards with fsrs_state === 'review' have graduated from the learning phase
 * and are treated as mastered for heuristic purposes.
 */
export function computeMasteryPct(cards: { fsrs_state: string }[]): number {
  if (cards.length === 0) return 0
  const mastered = cards.filter((c) => c.fsrs_state === "review").length
  return (mastered / cards.length) * 100
}

/**
 * Get the display name for a deck.
 * When a deck is named 'default' and it is the only deck for its document,
 * return the document title as a display alias (DB value unchanged).
 */
export function getDeckDisplayName(params: {
  deckName: string
  documentId: string | null
  docTitle: string | undefined
  isOnlyDeckForDocument: boolean
}): string {
  const { deckName, documentId, docTitle, isOnlyDeckForDocument } = params
  if (deckName !== "default") return deckName
  if (!documentId || !isOnlyDeckForDocument) return deckName
  return docTitle ?? deckName
}
