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

// ---------------------------------------------------------------------------
// S184: Flashcard search constants and helpers
// ---------------------------------------------------------------------------

export const FSRS_STATE_LABELS: Record<string, string> = {
  new: "New",
  learning: "Learning",
  review: "Review",
  relearning: "Relearning",
}

export const BLOOM_LEVEL_LABELS: Record<number, string> = {
  1: "Remember",
  2: "Understand",
  3: "Apply",
  4: "Analyze",
  5: "Evaluate",
  6: "Create",
}

export interface FlashcardSearchFilters {
  query?: string
  document_id?: string
  collection_id?: string
  tag?: string
  bloom_level_min?: number
  bloom_level_max?: number
  fsrs_state?: string
  flashcard_type?: string
  // S143: filter to a specific document section. Used by the Chapter
  // Goals "Study" link to land on the deck filtered to one section.
  section_id?: string
  page?: number
  page_size?: number
}

// ---------------------------------------------------------------------------
// S185: Insights accordion sections and adaptive generate params
// ---------------------------------------------------------------------------

/** Load-bearing constant: InsightsAccordion uses this to enumerate its sections. */
export const INSIGHTS_SECTIONS = ["health_report", "bloom_audit", "struggling"] as const

export type InsightsSection = (typeof INSIGHTS_SECTIONS)[number]

export interface SmartGenerateParams {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
  difficulty: "easy" | "medium" | "hard"
  smart_mode: SmartMode
}

/**
 * Build the payload for adaptive flashcard generation.
 * The smart_mode is chosen based on mastery percentage:
 *   < 30%  -> basic
 *   30-69% -> feynman
 *   >= 70% -> cloze
 */
export function buildSmartGenerateParams(
  masteryPct: number,
  documentId: string,
): SmartGenerateParams {
  const smart_mode = selectSmartMode(masteryPct)
  return {
    document_id: documentId,
    scope: "full",
    section_heading: null,
    count: 10,
    difficulty: "medium",
    smart_mode,
  }
}

export function buildSearchParams(filters: FlashcardSearchFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.query) params.set("query", filters.query)
  if (filters.document_id) params.set("document_id", filters.document_id)
  if (filters.collection_id) params.set("collection_id", filters.collection_id)
  if (filters.tag) params.set("tag", filters.tag)
  if (filters.bloom_level_min != null) params.set("bloom_level_min", String(filters.bloom_level_min))
  if (filters.bloom_level_max != null) params.set("bloom_level_max", String(filters.bloom_level_max))
  if (filters.fsrs_state) params.set("fsrs_state", filters.fsrs_state)
  if (filters.flashcard_type) params.set("flashcard_type", filters.flashcard_type)
  if (filters.section_id) params.set("section_id", filters.section_id)
  if (filters.page != null) params.set("page", String(filters.page))
  if (filters.page_size != null) params.set("page_size", String(filters.page_size))
  return params
}
