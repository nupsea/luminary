/**
 * Reading a model comparison: what a run costs before you start it, and which
 * of its numbers are allowed to decide anything.
 *
 * Pure functions only — the component mounts them, vitest tests them (the
 * project's vitest runs in a node environment, so components are never
 * mounted in tests).
 */

import type { LabMetricRow, LabRun, LabRunSummary, LabTask } from "@/lib/modelLabApi"

/** Stage keys selected in the form, expanded to the task ids the API expects. */
export function expandTasks(selected: string[], qaDatasets: string[]): string[] {
  return selected.flatMap((key) => (key === "qa" ? qaDatasets.map((d) => `qa:${d}`) : [key]))
}

/**
 * Rough wall-clock for a run, in seconds.
 *
 * Stated up front because these runs are long — a four-model comparison across
 * every stage is hours, and finding that out by waiting is the worst way.
 */
export function estimateSeconds(
  tasks: LabTask[],
  selected: string[],
  qaDatasets: string[],
  modelCount: number,
  maxQuestions: number,
): number {
  const byKey = new Map(tasks.map((t) => [t.key, t]))
  let perModel = 0
  for (const key of selected) {
    if (key === "qa") {
      // The catalogue has no per-dataset qa entry until datasets are chosen, so
      // price it from the question count the form is asking for.
      perModel += qaDatasets.length * (maxQuestions || 40) * 32
      continue
    }
    perModel += byKey.get(key)?.typical_seconds ?? 0
  }
  return perModel * Math.max(modelCount, 1)
}

export function formatDuration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 90) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours}h ${rest}m` : `${hours}h`
}

/** Stages that write generated content into the library, given a selection. */
export function mutatingStages(tasks: LabTask[], selected: string[]): string[] {
  return tasks.filter((t) => selected.includes(t.key) && t.mutates_library).map((t) => t.label)
}

export function progressPct(run: Pick<LabRun, "total_units" | "completed_units">): number {
  if (run.total_units <= 0) return 0
  return Math.round((run.completed_units / run.total_units) * 100)
}

export function isTerminal(run: LabRun): boolean {
  return run.status !== "running"
}

/** Rows grouped by tier, in the order they should be read. */
export function rowsByTier(rows: LabMetricRow[]): {
  tier: LabMetricRow["tier"]
  heading: string
  note: string
  rows: LabMetricRow[]
}[] {
  const groups: { tier: LabMetricRow["tier"]; heading: string; note: string }[] = [
    {
      tier: "structural",
      heading: "Structural — decides a swap",
      note: "What the model emitted before anything repaired it, how much of what was asked for arrived, and what the deterministic gates rejected.",
    },
    {
      tier: "quality",
      heading: "Quality — report only",
      note: "Never gates. A cross-model faithfulness delta is a style artifact; this repo spent a model decision learning that.",
    },
    {
      tier: "other",
      heading: "Other",
      note: "Recorded but not classified into a tier.",
    },
  ]
  return groups
    .map((g) => ({ ...g, rows: rows.filter((r) => r.tier === g.tier) }))
    .filter((g) => g.rows.length > 0)
}

/** A rate reads as a percentage, a count as itself. */
export function formatMetric(metric: string, value: number | null): string {
  if (value === null) return "—"
  if (
    metric.endsWith("_rate") ||
    metric.endsWith("_coverage") ||
    metric.endsWith("_accuracy")
  ) {
    return `${(value * 100).toFixed(1)}%`
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(4)
}

/**
 * The honest one-line verdict for a finished run.
 *
 * "Separated" is a claim about the instrument as much as the models: when
 * nothing separates them, the right conclusion is that this instrument cannot
 * tell them apart, never that the models are equivalent.
 */
export function verdict(
  run: LabRun | LabRunSummary,
): { tone: "good" | "warn" | "bad"; text: string } {
  const separated =
    "separation" in run ? (run.separation?.separated ?? null) : run.separated
  const count =
    "separation" in run
      ? (run.separation?.separating_metrics.length ?? 0)
      : run.separating_count

  if (run.status === "running") return { tone: "warn", text: "Running…" }
  if (run.status === "cancelled") {
    return { tone: "warn", text: "Cancelled — partial results are not a comparison." }
  }
  if (run.status === "failed") {
    return { tone: "bad", text: run.error ?? "The run failed." }
  }
  if (run.models.length < 2) {
    return { tone: "warn", text: "One model measured — nothing to compare it against." }
  }
  if (separated === null) {
    return { tone: "warn", text: "No separation computed." }
  }
  if (separated) {
    return { tone: "good", text: `Separated on ${count} structural metric(s).` }
  }
  return {
    tone: "bad",
    text: "Not separated. That is a finding about the instrument, not the models — add metrics until it can tell them apart, and do not choose a model on it meanwhile.",
  }
}
