/**
 * Per-kind eval matrix: one row per dataset, and the rules for when two rows
 * may be read side by side.
 *
 * Retrieval quality is a property of the writing, not a single number for the
 * product: measured on one funnel, HR@5 runs 0.35 on epistolary fiction to 1.00
 * on personal notes. A mean across datasets hides which kind moved, which is why
 * this is a table rather than a headline.
 *
 * Comparability is the other half. Re-ingesting one document has moved an
 * untouched document's MRR by as much as a model change did, so rows measured
 * against different corpora or different models are grouped apart rather than
 * ranked together.
 */

import type { EvalRunFull } from "@/components/evals/types"

/** Metric keys that have their own column; everything else is rendered generically. */
const NAMED_METRICS = new Set([
  "hit_rate_5",
  "mrr",
  "ndcg_10",
  "environment",
  "rerank",
])

export interface RunEnvironment {
  library?: { documents?: number; chunks?: number }
  chat_model?: string
  generation_model?: string
  embedding_model?: string
  rerank_model?: string
  backend_version?: string
  eval_git_sha?: string
  self_judged?: boolean
  scope?: string
  capture_error?: string
}

export interface KindRow {
  dataset: string
  runId: string
  runAt: string
  kind: string | null
  hitRate5: number | null
  mrr: number | null
  ndcg10: number | null
  boundaryMisses: number | null
  environment: RunEnvironment | null
  /** Any metric without a column, so a newly added one shows up unedited. */
  extras: [string, number | boolean | string][]
}

export function environmentOf(run: EvalRunFull): RunEnvironment | null {
  const env = run.extra_metrics?.environment
  return env && typeof env === "object" ? (env as RunEnvironment) : null
}

/**
 * What must match for two rows to mean the same thing. Corpus and funnel decide
 * retrieval; the models decide anything generated. `eval_git_sha` deliberately
 * does not: a commit touching neither pipeline nor corpus changes nothing.
 */
export function fingerprintOf(run: EvalRunFull): string {
  const env = environmentOf(run)
  if (!env) return "unrecorded"
  const lib = env.library ?? {}
  return [
    lib.documents ?? "?",
    lib.chunks ?? "?",
    env.embedding_model ?? "?",
    env.rerank_model ?? "?",
    env.chat_model ?? "?",
  ].join(" · ")
}

export function describeFingerprint(run: EvalRunFull): string {
  const env = environmentOf(run)
  if (!env) return "no provenance recorded"
  const lib = env.library ?? {}
  const docs = lib.documents ?? "?"
  const chunks = lib.chunks == null ? "?" : lib.chunks.toLocaleString()
  return `${docs} docs · ${chunks} chunks · ${env.embedding_model ?? "?"}`
}

function numberOr(value: unknown): number | null {
  return typeof value === "number" ? value : null
}

/** The newest run per dataset that carries retrieval numbers. */
export function latestRetrievalPerDataset(runs: EvalRunFull[]): EvalRunFull[] {
  const newest = new Map<string, EvalRunFull>()
  for (const run of runs) {
    if (run.status === "failed") continue
    if (run.hit_rate_5 == null && run.mrr == null) continue
    // Ablation rows carry per-arm numbers rather than one measurement, and a
    // series row is an aggregate of runs already in this list.
    if (run.eval_kind === "ablation") continue
    if (run.eval_kind?.endsWith("-series")) continue
    const key = run.dataset_label || run.dataset_name
    const seen = newest.get(key)
    if (!seen || Date.parse(run.run_at) > Date.parse(seen.run_at)) newest.set(key, run)
  }
  return [...newest.values()]
}

export function toKindRow(run: EvalRunFull, kind: string | null = null): KindRow {
  const extra = run.extra_metrics ?? {}
  const extras = Object.entries(extra)
    .filter(([key, value]) => !NAMED_METRICS.has(key) && typeof value !== "object")
    .sort(([a], [b]) => a.localeCompare(b)) as [string, number | boolean | string][]
  return {
    dataset: run.dataset_label || run.dataset_name,
    runId: run.id,
    runAt: run.run_at,
    kind,
    hitRate5: run.hit_rate_5,
    mrr: run.mrr,
    ndcg10: numberOr(extra.ndcg_10),
    boundaryMisses: numberOr(extra.boundary_misses),
    environment: environmentOf(run),
    extras,
  }
}

export interface ComparableGroup {
  fingerprint: string
  label: string
  rows: KindRow[]
}

/**
 * Rows grouped by what they were measured against, each group sorted worst
 * first — the kinds that need work read at the top rather than being buried
 * under the ones that already score well.
 */
export function groupByComparability(runs: EvalRunFull[]): ComparableGroup[] {
  const groups = new Map<string, { label: string; runs: EvalRunFull[] }>()
  for (const run of runs) {
    const key = fingerprintOf(run)
    const group = groups.get(key) ?? { label: describeFingerprint(run), runs: [] }
    group.runs.push(run)
    groups.set(key, group)
  }
  return [...groups.entries()]
    .map(([fingerprint, group]) => ({
      fingerprint,
      label: group.label,
      rows: group.runs
        .map((r) => toKindRow(r))
        .sort((a, b) => (a.hitRate5 ?? 1) - (b.hitRate5 ?? 1)),
    }))
    .sort((a, b) => b.rows.length - a.rows.length)
}

/** True when the visible rows were not all measured against the same system. */
export function isMixed(groups: ComparableGroup[]): boolean {
  return groups.length > 1
}
