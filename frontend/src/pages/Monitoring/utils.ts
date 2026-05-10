// Pure helpers (data shape transforms + colour mappers + threshold
// constants) consumed by the Monitoring page sub-components. No
// React, no fetches.

import type { EvalHistoryItem, EvalRun, ModelUsageItem } from "./types"

// ---------------------------------------------------------------------------
// Colour palettes
// ---------------------------------------------------------------------------

export const DATASET_COLORS: Record<string, string> = {
  book: "#6366f1",
  book_time_machine: "#8b5cf6",
  book_alice: "#ec4899",
  book_odyssey: "#f97316",
  paper: "#0ea5e9",
  notes: "#22c55e",
  conversation: "#f59e0b",
  code: "#a78bfa",
}

export const METRIC_BARS = [
  { key: "hit_rate_5", label: "HR@5", color: "#6366f1" },
  { key: "mrr", label: "MRR", color: "#0ea5e9" },
  { key: "faithfulness", label: "Faithfulness", color: "#22c55e" },
  { key: "answer_relevance", label: "Answer Rel.", color: "#f59e0b" },
  { key: "context_precision", label: "Ctx Prec.", color: "#ec4899" },
]

export const PIE_COLORS = ["#6366f1", "#0ea5e9", "#22c55e", "#f59e0b", "#ec4899"]

export const EVAL_THRESHOLDS: Record<string, number> = {
  hit_rate_5: 0.6,
  mrr: 0.45,
  faithfulness: 0.65,
  context_precision: 0.65,
}

// ---------------------------------------------------------------------------
// Chart data builders
// ---------------------------------------------------------------------------

export function buildSparklineData(history: EvalHistoryItem[]) {
  const datasets = Array.from(new Set(history.map((h) => h.dataset)))
  const allTimestamps = Array.from(new Set(history.map((h) => h.timestamp))).sort()
  return allTimestamps.map((ts, i) => {
    const row: Record<string, number | string> = { run: i + 1, ts }
    for (const ds of datasets) {
      const item = history.find((h) => h.timestamp === ts && h.dataset === ds)
      if (item && item.hr5 !== null) {
        row[ds] = item.hr5
      }
    }
    return row
  })
}

export function buildRagChartData(evalRuns: EvalRun[]) {
  const byDataset: Record<string, EvalRun> = {}
  for (const run of evalRuns) {
    if (!byDataset[run.dataset_name]) {
      byDataset[run.dataset_name] = run
    }
  }
  return Object.entries(byDataset).map(([dataset, run]) => ({
    dataset,
    hit_rate_5: run.hit_rate_5 ?? 0,
    mrr: run.mrr ?? 0,
    faithfulness: run.faithfulness ?? 0,
    answer_relevance: run.answer_relevance ?? 0,
    context_precision: run.context_precision ?? 0,
  }))
}

export function buildPieData(modelUsage: ModelUsageItem[]) {
  const local = modelUsage
    .filter((m) => m.model.startsWith("ollama/"))
    .reduce((s, m) => s + m.call_count, 0)
  const cloud = modelUsage
    .filter((m) => !m.model.startsWith("ollama/"))
    .reduce((s, m) => s + m.call_count, 0)
  return [
    { name: "Local (Ollama)", value: local },
    { name: "Cloud", value: cloud },
  ].filter((d) => d.value > 0)
}

// ---------------------------------------------------------------------------
// Score / mastery colour mappers
// ---------------------------------------------------------------------------

export function scoreColor(value: number | null, metricKey: string): string {
  if (value === null) return "text-muted-foreground"
  const threshold = EVAL_THRESHOLDS[metricKey]
  if (threshold === undefined) return "text-foreground"
  if (value >= threshold) return "text-green-700 dark:text-green-400 font-semibold"
  if (value >= threshold * 0.75) return "text-amber-600 dark:text-amber-400 font-semibold"
  return "text-muted-foreground"
}

export function masteryColor(mastery: number | null): string {
  if (mastery === null) return "bg-gray-100 dark:bg-gray-800"
  if (mastery < 0.3) return "bg-blue-200 dark:bg-blue-900"
  if (mastery < 0.6) return "bg-blue-400 dark:bg-blue-700"
  if (mastery < 0.8) return "bg-green-400 dark:bg-green-700"
  return "bg-green-600 dark:bg-green-500"
}
