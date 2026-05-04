// ---------------------------------------------------------------------------
// GoalProgressBar (S211) -- bar + label showing goal progress.
// ---------------------------------------------------------------------------

import { Progress } from "@/components/ui/progress"
import {
  progressLabel,
  progressPercent,
} from "@/components/goals/goalTypeMeta"
import type { Goal, GoalProgressMetrics } from "@/lib/goalsApi"

interface Props {
  goal: Goal
  metrics: GoalProgressMetrics | undefined
  loading?: boolean
  errored?: boolean
}

export function GoalProgressBar({ goal, metrics, loading, errored }: Props) {
  if (loading) {
    return (
      <div className="flex flex-col gap-1" aria-label="Loading goal progress">
        <div className="h-3 w-24 animate-pulse rounded bg-muted" />
        <div className="h-2 w-full animate-pulse rounded-full bg-muted" />
      </div>
    )
  }
  if (errored || !metrics) {
    return (
      <div role="alert" className="text-[11px] text-destructive">
        Could not load progress
      </div>
    )
  }
  const label = progressLabel(
    goal.goal_type,
    metrics,
    goal.target_value,
    goal.target_unit,
  )
  const pct = progressPercent(metrics)
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{label}</span>
        <span className="tabular-nums">{pct.toFixed(0)}%</span>
      </div>
      <Progress value={pct} />
    </div>
  )
}
