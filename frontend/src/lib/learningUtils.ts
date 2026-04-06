/**
 * Pure utility functions for the Learning tab stats bar.
 * No DOM/React imports -- testable in Vitest node env.
 * Per patterns.md: Vitest node env + DOM events pure utility pattern.
 */

export type StatPill = "study" | "notes" | "progress"

export interface StatPillNavigateDetail {
  tab: StatPill
}

/**
 * Build the detail payload for a luminary:navigate event targeting a tab.
 * Used by stat pills in LibraryStatsBar.
 */
export function buildStatPillNavigateDetail(pill: StatPill): StatPillNavigateDetail {
  return { tab: pill }
}

export const STAT_PILL_LABELS = {
  books: "books",
  notes: "notes",
  mastery: "avg mastery",
  due: "cards due",
} as const

/**
 * Compute average mastery from a list of session accuracy percentages.
 * Returns null if no sessions have accuracy data.
 */
export function computeAvgMastery(accuracyValues: (number | null)[]): number | null {
  const valid = accuracyValues.filter((v): v is number => v !== null)
  if (valid.length === 0) return null
  const sum = valid.reduce((a, b) => a + b, 0)
  return Math.round(sum / valid.length)
}

/**
 * Return the most recently viewed document from a list sorted by last_accessed_at desc.
 * The backend returns items sorted by last_accessed when sort=last_accessed, so the
 * first item is always the most recently viewed. Returns null if list is empty.
 */
export function getMostRecentDocument<T>(items: T[]): T | null {
  return items.length > 0 ? items[0] : null
}
