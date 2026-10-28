import type { Flashcard } from "@/lib/studyApi"

/** Cards each chapter contributes to an all-chapters run unless the learner picks another count. */
export const DEFAULT_CARDS_PER_CHAPTER = 2
export const CARDS_PER_CHAPTER_CHOICES = [1, 2, 3, 5] as const

// due_date arrives as naive UTC ("2026-10-28T02:59:05.526458"), so it is compared as text
// against UTC now; `new Date()` would read it as local time.
function isDue(card: Flashcard, nowIso: string): boolean {
  return card.due_date == null || card.due_date.slice(0, 19) <= nowIso.slice(0, 19)
}

/**
 * The `k` cards of one chapter most worth a learner's time: due before not yet due, then the
 * weakest first. A card whose quote or answer was checked and failed is never picked.
 */
export function topCards(cards: Flashcard[], k: number, now: Date = new Date()): Flashcard[] {
  const nowIso = now.toISOString()
  const due = (c: Flashcard) => (isDue(c, nowIso) ? 0 : 1)
  return cards
    .filter((c) => c.grounding !== "unsupported" && c.factuality !== "unsupported")
    .sort((a, b) => due(a) - due(b) || a.fsrs_stability - b.fsrs_stability)
    .slice(0, k)
}
