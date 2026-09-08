/**
 * Shared recall-loop feedback: what a grade is called, and what the learner's
 * pre-reveal prediction turned out to be worth.
 *
 * The Study page and the reader's Practice face run the same loop at different
 * sizes. Only the layout differs. A grade must not read "Good" on one surface
 * and "Got it" on the other, and calibration must be scored identically on
 * both -- it is the measurement the learner record is built on, so two copies
 * of this arithmetic would be two different claims about the same person.
 */

import type { Rating } from "@/lib/studyApi"

export type ConfidenceBucket = "knew" | "unsure" | "blank"
export type CalibrationTone = "positive" | "warn" | "info" | "neutral"

export const RATING_ORDER: readonly Rating[] = ["again", "hard", "good", "easy"]

export const RATING_LABELS: Record<Rating, string> = {
  again: "Again",
  hard: "Hard",
  good: "Good",
  easy: "Easy",
}

// Each grade also carries a distinct icon at the call site so Again/Good aren't
// told apart by hue alone (red-green colour-vision deficiency is the common case).
export const RATING_CLASS: Record<Rating, string> = {
  again: "bg-red-100 text-red-700 border-red-200 hover:bg-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900 dark:hover:bg-red-900/50",
  hard: "bg-orange-100 text-orange-700 border-orange-200 hover:bg-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-900 dark:hover:bg-orange-900/50",
  good: "bg-green-100 text-green-700 border-green-200 hover:bg-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900 dark:hover:bg-green-900/50",
  easy: "bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900 dark:hover:bg-blue-900/50",
}

/**
 * The commitment the learner makes while the answer is still unrendered.
 *
 * Three points, not four: before seeing the answer nobody can tell "Good" from
 * "Easy", and asking for a distinction that fine invents a number rather than
 * measuring one. Encoded as FSRS ratings so `ratingBucket` compares the
 * prediction and the grade on one scale.
 */
export const PREDICTIONS: readonly { value: Rating; label: string }[] = [
  { value: "again", label: "Blank" },
  { value: "hard", label: "Unsure" },
  { value: "good", label: "Know it" },
]

export function ratingBucket(r: Rating): ConfidenceBucket {
  if (r === "good" || r === "easy") return "knew"
  if (r === "hard") return "unsure"
  return "blank"
}

/**
 * Compare the pre-reveal prediction (3-point) against the grade given after
 * seeing the answer (4-point FSRS). "Calibrated" means both land in the same
 * confidence bucket; the copy names the direction of the miss.
 */
export function calibrationMessage(
  predicted: Rating,
  actual: Rating,
): { text: string; tone: CalibrationTone; calibrated: boolean } {
  const p = ratingBucket(predicted)
  const a = ratingBucket(actual)
  if (p === a) return { text: "Well calibrated.", tone: "positive", calibrated: true }
  const order = { blank: 0, unsure: 1, knew: 2 } as const
  if (order[p] > order[a]) {
    return { text: "Overconfident — you predicted you knew it.", tone: "warn", calibrated: false }
  }
  return { text: "You knew more than you thought.", tone: "info", calibrated: false }
}

export const CALIBRATION_TEXT_CLASS: Record<CalibrationTone, string> = {
  positive: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  info: "text-blue-600 dark:text-blue-400",
  neutral: "text-muted-foreground",
}

export function getSessionPhase(
  index: number,
  total: number,
): { label: string; style: string } {
  if (total <= 3) return { label: "Review", style: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" }
  const pct = index / total
  if (pct < 0.25) return { label: "Warm-up", style: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" }
  if (pct < 0.85) return { label: "Engage", style: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" }
  return { label: "Reflect", style: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400" }
}
