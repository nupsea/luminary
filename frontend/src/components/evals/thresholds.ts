import type { AblationArm, EvalRunFull } from "./types"

// Single source of truth for eval quality gates. Must match the backend gates
// in evals/run_eval.py THRESHOLDS — do not fork per-view copies.
// ndcg_10 is provisional / report-only there too: shown against this bar but
// never asserted until graded goldens exist and baselines are recorded.
export const THRESHOLDS = {
  hit_rate_5: 0.5,
  mrr: 0.35,
  ndcg_10: 0.4,
  faithfulness: 0.65,
} as const

export function metricColor(v: number | null | undefined, threshold: number): string {
  if (v == null) return ""
  if (v >= threshold) return "font-semibold text-green-700 dark:text-green-400"
  if (v >= threshold * 0.75) return "font-semibold text-amber-600 dark:text-amber-400"
  return "text-muted-foreground"
}

export function timeAgo(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const mins = Math.round((now - then) / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 60) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export function isStale(iso: string, days = 14, now: number = Date.now()): boolean {
  const then = new Date(iso).getTime()
  return !Number.isNaN(then) && now - then > days * 86_400_000
}

// The arm of a strategy ablation that matches the shipped pipeline:
// rrf + rerank when measured, plain rrf otherwise.
export function shippedAblationArm(
  run: EvalRunFull,
): { label: string; arm: AblationArm } | null {
  const arms = run.ablation_metrics
  if (!arms) return null
  if (arms["rrf+rerank"]) return { label: "rrf+rerank", arm: arms["rrf+rerank"] }
  if (arms["rrf"]) return { label: "rrf", arm: arms["rrf"] }
  return null
}
