// ---------------------------------------------------------------------------
// goalTypeMeta (S211) -- pure helpers mapping goal types to display metadata
// and to the focus surface they expect. Kept as pure functions so vitest
// (node env) can cover them without DOM mounting.
// ---------------------------------------------------------------------------

import { BookOpen, Brain, Compass, Pencil, type LucideIcon } from "lucide-react"
import type { GoalType, GoalProgressMetrics, TargetUnit } from "@/lib/goalsApi"
import type { Surface } from "@/lib/focusUtils"

export const GOAL_TYPE_LABEL: Record<GoalType, string> = {
  read: "Read",
  recall: "Recall",
  write: "Write",
  explore: "Explore",
}

export const GOAL_TYPE_ICON: Record<GoalType, LucideIcon> = {
  read: BookOpen,
  recall: Brain,
  write: Pencil,
  explore: Compass,
}

// Map a goal type to the focus-pill surface that genuinely contributes to its
// progress. Returns "none" only if no surface meaningfully attributes.
export function expectedSurfaceForGoalType(goalType: GoalType): Surface {
  switch (goalType) {
    case "read":
      return "read"
    case "recall":
      return "recall"
    case "write":
      return "write"
    case "explore":
      return "explore"
  }
}

// Suggest a default target_unit per goal type. The user can still override.
export function defaultTargetUnitForGoalType(goalType: GoalType): TargetUnit {
  switch (goalType) {
    case "read":
      return "minutes"
    case "recall":
      return "cards"
    case "write":
      return "notes"
    case "explore":
      return "turns"
  }
}

// Render the progress label for a goal of the given type, given its metrics
// dict and (optional) target value+unit. Returns a single concise line.
export function progressLabel(
  goalType: GoalType,
  metrics: GoalProgressMetrics,
  targetValue: number | null,
  targetUnit: TargetUnit | null,
): string {
  const unit = targetUnit ?? defaultTargetUnitForGoalType(goalType)
  let actual: number
  switch (goalType) {
    case "read":
      actual = metrics.minutes_focused ?? 0
      break
    case "recall":
      actual = metrics.cards_reviewed ?? 0
      break
    case "write":
      actual = metrics.notes_created ?? 0
      break
    case "explore":
      actual = metrics.turns ?? 0
      break
  }
  if (targetValue === null || targetValue === undefined) {
    return `${actual} ${unit}`
  }
  return `${actual} / ${targetValue} ${unit}`
}

// Pct used to drive the progress bar; clamps 0..100, defaults to 0 when missing.
export function progressPercent(metrics: GoalProgressMetrics): number {
  const v = metrics.completed_pct
  if (v === undefined || v === null || Number.isNaN(v)) return 0
  return Math.max(0, Math.min(100, v))
}

// Surface mismatch test. Returns null when no warning should render, otherwise
// returns a short user-facing string.
export function surfaceMismatchWarning(
  goalType: GoalType,
  inferredSurface: Surface,
): string | null {
  const expected = expectedSurfaceForGoalType(goalType)
  if (inferredSurface === expected) return null
  // We only nag when the user is on one of the four learning surfaces and it
  // disagrees. Unknown surface ("none") is not flagged.
  if (inferredSurface === "none") return null
  return `This goal is ${expected} but the active tab is ${inferredSurface} -- progress may not count.`
}
