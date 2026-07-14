import { useState } from "react"
import { ArrowDown, ArrowDownRight, ArrowRight, ArrowUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { THRESHOLDS } from "./thresholds"
import type { AblationArm, EvalRunFull } from "./types"

type MetricKey = "hit_rate_5" | "mrr" | "ndcg_10"

const METRICS: { key: MetricKey; label: string; threshold: number }[] = [
  { key: "hit_rate_5", label: "HR@5", threshold: THRESHOLDS.hit_rate_5 },
  { key: "mrr", label: "MRR@5", threshold: THRESHOLDS.mrr },
  { key: "ndcg_10", label: "nDCG@10", threshold: THRESHOLDS.ndcg_10 },
]

// The pipeline as the reader should walk it: pick a single signal, fuse the
// signals, then re-score the fused pool. Each stage lists the arms measured for
// it; the shipped arm is the last step of the last stage.
const STAGES: { id: string; label: string; hint: string; arms: string[] }[] = [
  {
    id: "single",
    label: "1 · Single retriever",
    hint: "one signal, no fusion — the choice of base retriever",
    arms: ["vector", "fts", "graph"],
  },
  {
    id: "fusion",
    label: "2 · Reciprocal-rank fusion",
    hint: "combine every signal into one ranked pool",
    arms: ["rrf"],
  },
  {
    id: "rerank",
    label: "3 · Cross-encoder rerank",
    hint: "re-score the fused pool with the cross-encoder",
    arms: ["rrf+rerank-ce", "rrf+rerank"],
  },
]

const ARM_LABEL: Record<string, string> = {
  vector: "Vector (embeddings)",
  fts: "Full-text (BM25)",
  graph: "Graph",
  rrf: "RRF fusion",
  "rrf+rerank-ce": "+ Rerank (CE only)",
  "rrf+rerank": "+ Rerank (blended)",
}

const SHIPPED_ARM = "rrf+rerank"

const INCREMENTS: { from: string; to: string; label: string }[] = [
  { from: "single", to: "fusion", label: "Fusion over best single retriever" },
  { from: "fusion", to: "rerank", label: "Rerank over fusion" },
]

function metricOf(arm: AblationArm | undefined, key: MetricKey): number | null {
  if (!arm) return null
  const v = key === "ndcg_10" ? arm.ndcg_10 : arm[key]
  return typeof v === "number" ? v : null
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`
}

function pts(v: number): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}`
}

// Best value reached anywhere within a stage, on the active metric — this is
// what the next stage has to beat for its increment chip to read positive.
function stageBest(
  arms: Record<string, AblationArm>,
  stageId: string,
  metric: MetricKey,
): number | null {
  const stage = STAGES.find((s) => s.id === stageId)
  if (!stage) return null
  let best: number | null = null
  for (const key of stage.arms) {
    const v = metricOf(arms[key], metric)
    if (v != null && (best == null || v > best)) best = v
  }
  return best
}

function IncrementChip({ delta, label }: { delta: number | null; label: string }) {
  if (delta == null) return null
  const positive = delta > 0.0005
  const negative = delta < -0.0005
  const Icon = positive ? ArrowUp : negative ? ArrowDown : ArrowRight
  const tone = positive
    ? "text-emerald-600 dark:text-emerald-400"
    : negative
      ? "text-red-600 dark:text-red-400"
      : "text-muted-foreground"
  return (
    <div className="flex items-center gap-2 py-2 pl-[184px]">
      <ArrowDownRight className="h-3.5 w-3.5 text-muted-foreground/50" />
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span
        className={cn(
          "inline-flex items-center gap-0.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold tabular-nums",
          tone,
        )}
      >
        <Icon className="h-3 w-3" />
        {pts(delta)} pts
      </span>
    </div>
  )
}

function ArmBar({
  armKey,
  arm,
  metric,
  ceiling,
  isBestSingle,
}: {
  armKey: string
  arm: AblationArm | undefined
  metric: MetricKey
  ceiling: number | null
  isBestSingle: boolean
}) {
  const value = metricOf(arm, metric)
  const shipped = armKey === SHIPPED_ARM
  const width = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100
  const gate = METRICS.find((m) => m.key === metric)?.threshold ?? 0
  const other = METRICS.filter((m) => m.key !== metric)
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="flex w-[184px] shrink-0 items-center gap-1.5">
        <span
          className={cn(
            "truncate text-xs",
            shipped ? "font-semibold text-foreground" : "text-muted-foreground",
          )}
          title={ARM_LABEL[armKey] ?? armKey}
        >
          {ARM_LABEL[armKey] ?? armKey}
        </span>
        {shipped && (
          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
            shipped
          </span>
        )}
        {isBestSingle && !shipped && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
            best
          </span>
        )}
      </div>

      <div
        className="relative h-6 flex-1 overflow-hidden rounded bg-muted/50"
        title={`${ARM_LABEL[armKey] ?? armKey} — ${METRICS.find((m) => m.key === metric)?.label}: ${pct(value)}`}
      >
        <div
          className={cn(
            "absolute inset-y-0 left-0 rounded-r",
            shipped
              ? "bg-indigo-600 dark:bg-indigo-400"
              : "bg-indigo-500/70 dark:bg-indigo-400/60",
          )}
          style={{ width: `${width}%` }}
        />
        {/* gate threshold — hairline, always shown */}
        <div
          className="absolute inset-y-0 w-px bg-foreground/25"
          style={{ left: `${gate * 100}%` }}
          title={`gate ≥ ${(gate * 100).toFixed(0)}%`}
        />
        {/* L1 pool recall ceiling — only meaningful for HR@5 (a recall proxy) */}
        {metric === "hit_rate_5" && ceiling != null && (
          <div
            className="absolute inset-y-0 w-px bg-amber-500/70"
            style={{ left: `${ceiling * 100}%` }}
            title={`L1 pool recall ceiling ${(ceiling * 100).toFixed(0)}%`}
          />
        )}
      </div>

      <div className="flex w-[172px] shrink-0 items-baseline justify-end gap-2">
        <span
          className={cn(
            "text-sm font-semibold tabular-nums",
            value == null ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {pct(value)}
        </span>
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {other.map((m) => `${m.label} ${pct(metricOf(arm, m.key))}`).join(" · ")}
        </span>
      </div>
    </div>
  )
}

function PoolRecall({ pool }: { pool: AblationArm }) {
  const depths = Object.keys(pool)
    .filter((k) => k.startsWith("recall_"))
    .map((k) => Number(k.slice("recall_".length)))
    .filter((d) => Number.isFinite(d))
    .sort((a, b) => a - b)
  if (!depths.length) return null
  return (
    <div className="mt-4 rounded-md border border-dashed p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">L1 candidate-pool recall</span>
        <span className="text-[11px] text-muted-foreground">
          ceiling the reranker can reach — gold present in the raw RRF pool
        </span>
      </div>
      <div className="grid gap-1.5">
        {depths.map((d) => {
          const v = pool[`recall_${d}`]
          const width = typeof v === "number" ? Math.max(0, Math.min(1, v)) * 100 : 0
          return (
            <div key={d} className="flex items-center gap-3">
              <span className="w-16 shrink-0 text-[11px] tabular-nums text-muted-foreground">
                @{d}
              </span>
              <div className="relative h-3.5 flex-1 overflow-hidden rounded bg-muted/50">
                <div
                  className="absolute inset-y-0 left-0 rounded-r bg-amber-500/60"
                  style={{ width: `${width}%` }}
                />
              </div>
              <span className="w-12 shrink-0 text-right text-[11px] font-medium tabular-nums text-foreground">
                {pct(typeof v === "number" ? v : null)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function StrategyFunnel({ run }: { run: EvalRunFull }) {
  const [metric, setMetric] = useState<MetricKey>("hit_rate_5")
  const arms = run.ablation_metrics
  if (!arms) return null

  const pool = arms["rrf-pool"] as AblationArm | undefined
  const ceiling = pool
    ? (() => {
        const depths = Object.keys(pool)
          .filter((k) => k.startsWith("recall_"))
          .map((k) => Number(k.slice("recall_".length)))
          .filter((d) => Number.isFinite(d))
          .sort((a, b) => b - a)
        const top = depths[0]
        const v = top != null ? pool[`recall_${top}`] : null
        return typeof v === "number" ? v : null
      })()
    : null

  // The single retriever that wins on the active metric gets the "best" tag —
  // it is the one fusion is really competing against.
  const singleStage = STAGES[0]
  let bestSingleKey: string | null = null
  let bestSingleVal = -1
  for (const key of singleStage.arms) {
    const v = metricOf(arms[key], metric)
    if (v != null && v > bestSingleVal) {
      bestSingleVal = v
      bestSingleKey = key
    }
  }

  const ceOnly = arms["rrf+rerank-ce"]
  const blended = arms[SHIPPED_ARM]
  const blendGain =
    ceOnly && blended
      ? (metricOf(blended, metric) ?? 0) - (metricOf(ceOnly, metric) ?? 0)
      : null

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Retrieval strategy funnel</h3>
        <div className="flex items-center gap-2">
          <div className="inline-flex overflow-hidden rounded-md border">
            {METRICS.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => setMetric(m.key)}
                className={cn(
                  "px-2.5 py-1 text-[11px] font-medium transition-colors",
                  metric === m.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-background text-muted-foreground hover:text-foreground",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {new Date(run.run_at).toLocaleString()}
          </span>
        </div>
      </div>
      <p className="mb-4 text-[11px] text-muted-foreground">
        Each bar is one retrieval strategy on the same golden set. Walk it top to bottom to see
        what each choice adds; the chips between stages are the increment on{" "}
        {METRICS.find((m) => m.key === metric)?.label}.
      </p>

      <div className="grid gap-3">
        {STAGES.map((stage, i) => {
          const stageArms = stage.arms.filter((k) => arms[k])
          if (!stageArms.length) return null
          const inc = INCREMENTS.find((x) => x.to === stage.id)
          const delta =
            inc != null
              ? (() => {
                  const from = stageBest(arms, inc.from, metric)
                  const to = stageBest(arms, inc.to, metric)
                  return from != null && to != null ? to - from : null
                })()
              : null
          return (
            <div key={stage.id}>
              {i > 0 && inc && <IncrementChip delta={delta} label={inc.label} />}
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground/70">
                  {stage.label}
                </span>
                <span className="text-[10px] text-muted-foreground">{stage.hint}</span>
              </div>
              {stageArms.map((key) => (
                <ArmBar
                  key={key}
                  armKey={key}
                  arm={arms[key]}
                  metric={metric}
                  ceiling={ceiling}
                  isBestSingle={key === bestSingleKey}
                />
              ))}
            </div>
          )
        })}
      </div>

      {blendGain != null && (
        <p className="mt-3 text-[11px] text-muted-foreground">
          Blending the RRF rank back into the cross-encoder score adds{" "}
          <span
            className={cn(
              "font-semibold tabular-nums",
              blendGain > 0.0005
                ? "text-emerald-600 dark:text-emerald-400"
                : blendGain < -0.0005
                  ? "text-red-600 dark:text-red-400"
                  : "text-muted-foreground",
            )}
          >
            {pts(blendGain)} pts
          </span>{" "}
          over the cross-encoder alone on {METRICS.find((m) => m.key === metric)?.label}.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-indigo-600 dark:bg-indigo-400" />
          shipped arm
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-indigo-500/70 dark:bg-indigo-400/60" />
          other arms
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-px bg-foreground/25" />
          gate threshold
        </span>
        {metric === "hit_rate_5" && ceiling != null && (
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-px bg-amber-500/70" />
            L1 pool ceiling
          </span>
        )}
      </div>

      {pool && <PoolRecall pool={pool} />}
    </div>
  )
}
