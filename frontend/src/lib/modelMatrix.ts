/**
 * Which model produced which numbers, side by side.
 *
 * Only the structural tier appears: repair counters, delivery, shape adherence,
 * the deterministic card gate, routing accuracy against a labelled golden.
 * Judged scores are excluded because a cross-model delta in them is a style
 * artifact — this repo spent a model decision learning that — and retrieval
 * metrics are excluded because they have no generation-model term at all, so
 * including them lets corpus noise read as a model difference.
 *
 * Two guards travel with the table. Runs measured against different corpora or
 * funnels are not comparable and are labelled rather than ranked. And a metric
 * that came out bit-identical on two different models did not measure the
 * model: two models do not produce the same float to full precision on work
 * that depends on them, so "identical" means something replayed a stored
 * artifact, not that the models are equivalent.
 */

import type { EvalRunFull } from "@/components/evals/types"
import { environmentOf, fingerprintOf } from "@/lib/evalMatrix"

/** Metric keys the structural tier is allowed to show. Mirrors evals/lib/matrix.py. */
const STRUCTURAL = new Set([
  "first_pass_rate",
  "parse_failure_rate",
  "shape_deviation_rate",
  "shape_deviations",
  "card_reject_rate",
  "cards_gated",
  "cards_rejected",
  "cards_requested",
  "cards_generated",
  "generation_rate",
  "answer_rate",
  "citation_coverage",
  "citations_dropped",
  "citations_proposed",
  "citations_gated",
  "uncited_answers",
  "qa_failed_calls",
  "qa_not_found_calls",
  "qa_answered_calls",
  "routing_accuracy",
])

const STRUCTURAL_PREFIXES = ["repair_", "card_reject_"]

/**
 * Structural in shape, decided by library state rather than by the model: the
 * near-duplicate filter drops cards resembling ones the document already has,
 * so the same passage yields fewer on every re-run.
 */
const LIBRARY_STATE_DEPENDENT = new Set(["cards_returned", "cards_deduped"])

export function isStructural(key: string): boolean {
  if (LIBRARY_STATE_DEPENDENT.has(key)) return false
  return STRUCTURAL.has(key) || STRUCTURAL_PREFIXES.some((p) => key.startsWith(p))
}

export interface ModelCell {
  model: string
  value: number
}

export interface ModelMetricRow {
  /** `<eval kind>.<metric>` — the metric alone is ambiguous across kinds. */
  key: string
  kind: string
  metric: string
  cells: Record<string, number>
  /** True when every model that reported this metric reported the same value. */
  identical: boolean
}

export interface ModelMatrix {
  models: string[]
  rows: ModelMetricRow[]
  /** Distinct provenance fingerprints across the runs feeding this table. */
  fingerprints: string[]
  /** Metric keys whose value never moved between models. */
  identicalKeys: string[]
}

function resolvedModel(run: EvalRunFull): string | null {
  const env = environmentOf(run)
  // The generation model is what wrote anything being scored structurally; chat
  // is the fallback for kinds that do not generate (routing).
  return env?.generation_model ?? env?.chat_model ?? null
}

function numericMetrics(run: EvalRunFull): Record<string, number> {
  const out: Record<string, number> = {}
  const extras = run.extra_metrics ?? {}
  for (const [key, value] of Object.entries(extras)) {
    if (typeof value === "number" && isStructural(key)) out[key] = value
  }
  if (typeof run.routing_accuracy === "number") out.routing_accuracy = run.routing_accuracy
  return out
}

/**
 * The newest run per (model, eval kind). A model's second run on the same kind
 * replaces its first; it does not become another column.
 */
export function buildModelMatrix(runs: EvalRunFull[]): ModelMatrix {
  const newest = new Map<string, EvalRunFull>()
  for (const run of runs) {
    if (run.status === "failed") continue
    const model = resolvedModel(run)
    if (!model) continue
    const kind = run.eval_kind ?? "run"
    const key = `${model}::${kind}`
    const seen = newest.get(key)
    if (!seen || Date.parse(run.run_at) > Date.parse(seen.run_at)) newest.set(key, run)
  }

  const models: string[] = []
  const fingerprints = new Set<string>()
  const cellsByKey = new Map<string, ModelMetricRow>()

  for (const [key, run] of [...newest.entries()].sort()) {
    const [model, kind] = key.split("::")
    const metrics = numericMetrics(run)
    if (Object.keys(metrics).length === 0) continue
    if (!models.includes(model)) models.push(model)
    fingerprints.add(fingerprintOf(run))
    for (const [metric, value] of Object.entries(metrics)) {
      const rowKey = `${kind}.${metric}`
      const row = cellsByKey.get(rowKey) ?? { key: rowKey, kind, metric, cells: {}, identical: false }
      row.cells[model] = value
      cellsByKey.set(rowKey, row)
    }
  }

  const rows = [...cellsByKey.values()]
    .map((row) => {
      const values = Object.values(row.cells)
      return {
        ...row,
        identical: values.length > 1 && values.every((v) => v === values[0]),
      }
    })
    .sort((a, b) => a.key.localeCompare(b.key))

  return {
    models,
    rows,
    fingerprints: [...fingerprints],
    identicalKeys: rows.filter((r) => r.identical).map((r) => r.key),
  }
}

/** How a structural value reads: a rate as a percentage, a count as itself. */
export function formatStructural(metric: string, value: number): string {
  if (metric.endsWith("_rate") || metric.endsWith("_coverage") || metric.endsWith("_accuracy")) {
    return `${(value * 100).toFixed(1)}%`
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(4)
}
