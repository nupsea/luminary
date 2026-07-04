import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowDown, ArrowRight, ArrowUp, Sparkles } from "lucide-react"
import { GenerateGoldenDialog } from "./GenerateGoldenDialog"
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"
import { isStale, shippedAblationArm, THRESHOLDS, timeAgo } from "./thresholds"
import type { EvalRunFull } from "./types"

const RETRIEVAL_KINDS = new Set(["retrieval", "generation", "citation", null])

interface GoldenInfo {
  name: string
  question_count: number
  source_file: string | null
  provenance: {
    generated_at?: string
    generator_model?: string
    verify_models?: string[]
    personas?: string[]
    accepted?: number
    flagged?: number
  } | null
  quality: {
    hint_verbatim_rate?: number
    self_contained_rate?: number
    answer_ok_rate?: number
    question_len_mean?: number
    question_len_std?: number
    distinct_personas?: number
    quality_score?: number
  } | null
}

async function fetchRuns(dataset: string): Promise<EvalRunFull[]> {
  const res = await fetch(
    `${API_BASE}/evals/runs?dataset_name=${encodeURIComponent(dataset)}&limit=50`,
  )
  if (!res.ok) throw new Error("Failed to fetch runs")
  return res.json() as Promise<EvalRunFull[]>
}

async function fetchGoldenInfo(dataset: string): Promise<GoldenInfo> {
  const res = await fetch(`${API_BASE}/evals/golden/${encodeURIComponent(dataset)}/info`)
  if (!res.ok) throw new Error("Failed to fetch golden info")
  return res.json() as Promise<GoldenInfo>
}

function GoldenCard({ dataset }: { dataset: string }) {
  const [genOpen, setGenOpen] = useState(false)
  const { data } = useQuery({
    queryKey: ["golden-info", dataset],
    queryFn: () => fetchGoldenInfo(dataset),
    enabled: Boolean(dataset),
    staleTime: 60_000,
  })
  if (!data) return null
  const p = data.provenance
  const q = data.quality
  const verbatim = q?.hint_verbatim_rate
  return (
    <div className="rounded-lg border bg-card p-4">
      <GenerateGoldenDialog
        open={genOpen}
        onOpenChange={setGenOpen}
        defaultName={dataset}
        defaultSourceFile={data.source_file ?? ""}
        onStarted={() => {}}
      />
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Golden dataset</h3>
        <div className="flex items-center gap-2">
          {p?.verify_models?.length ? (
            <span
              className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700"
              title={`Every pair passed independent verification by ${p.verify_models.join(", ")}`}
            >
              cross-verified
            </span>
          ) : (
            <span
              className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
              title="No provenance record — this golden was authored before the verified-generation pipeline. Regenerate to get persona-diverse, cross-verified questions."
            >
              legacy · unverified
            </span>
          )}
          {q?.quality_score != null && (
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                q.quality_score >= 0.9
                  ? "bg-green-100 text-green-700"
                  : q.quality_score >= 0.75
                    ? "bg-amber-100 text-amber-700"
                    : "bg-red-100 text-red-700",
              )}
            >
              quality {(q.quality_score * 100).toFixed(0)}%
            </span>
          )}
          <button
            type="button"
            onClick={() => setGenOpen(true)}
            disabled={!data.source_file}
            title={data.source_file ? "" : "No source file on record for this dataset"}
            className="inline-flex h-7 items-center gap-1 rounded border px-2 text-xs font-medium hover:bg-accent disabled:opacity-40"
          >
            <Sparkles className="h-3.5 w-3.5" />
            Regenerate
          </button>
        </div>
      </div>
      <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
        <div>
          <div>
            <span className="text-foreground">{data.question_count}</span> questions
            {p?.personas?.length ? ` · ${p.personas.length} personas` : ""}
          </div>
          {p?.generated_at && (
            <div>
              generated {new Date(p.generated_at).toLocaleDateString()}
              {p.generator_model ? ` · ${p.generator_model}` : ""}
            </div>
          )}
          {p?.verify_models?.length ? (
            <div>verified by {p.verify_models.join(" + ")}</div>
          ) : null}
          {p?.accepted != null && p?.flagged != null && (
            <div>
              {p.accepted} accepted · {p.flagged} flagged (rejected in verification)
            </div>
          )}
        </div>
        <div className="grid gap-1">
          {verbatim != null && (
            <div
              className={cn(
                "flex justify-between",
                verbatim < 1 ? "text-amber-600" : "",
              )}
            >
              <span>hint verbatim-in-source</span>
              <span className="tabular-nums">{(verbatim * 100).toFixed(0)}%</span>
            </div>
          )}
          {q?.self_contained_rate != null && (
            <div className="flex justify-between">
              <span>self-contained questions</span>
              <span className="tabular-nums">{(q.self_contained_rate * 100).toFixed(0)}%</span>
            </div>
          )}
          {q?.answer_ok_rate != null && (
            <div
              className={cn(
                "flex justify-between",
                q.answer_ok_rate < 1 ? "text-amber-600" : "",
              )}
            >
              <span>non-trivial answers (≥10 chars)</span>
              <span className="tabular-nums">{(q.answer_ok_rate * 100).toFixed(0)}%</span>
            </div>
          )}
          {q?.question_len_mean != null && (
            <div className="flex justify-between">
              <span>question length (words)</span>
              <span className="tabular-nums">
                {q.question_len_mean} ± {q.question_len_std}
              </span>
            </div>
          )}
          {q?.distinct_personas != null && q.distinct_personas > 0 && (
            <div className="flex justify-between">
              <span>reader personas</span>
              <span className="tabular-nums">{q.distinct_personas}</span>
            </div>
          )}
        </div>
      </div>
      {verbatim != null && verbatim < 1 && (
        <p className="mt-2 text-[11px] text-amber-600">
          {((1 - verbatim) * 100).toFixed(0)}% of hints are not verbatim in the source — those
          questions are unretrievable and unfairly lower HR@5/MRR.
        </p>
      )}
      {q?.answer_ok_rate != null && q.answer_ok_rate < 1 && (
        <p className="mt-2 text-[11px] text-amber-600">
          {((1 - q.answer_ok_rate) * 100).toFixed(0)}% of golden answers are under 10 characters —
          short factoids weaken generation judging. This is the component holding the quality
          score down.
        </p>
      )}
    </div>
  )
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`
}

function isRerank(r: EvalRunFull): boolean {
  return r.extra_metrics?.rerank === true
}

function MetricCard({
  label,
  value,
  threshold,
  hint,
  sub,
}: {
  label: string
  value: number | null | undefined
  threshold: number
  hint: string
  sub?: string | null
}) {
  const pass = value != null && value >= threshold
  const near = value != null && value >= threshold * 0.75
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {value != null && (
          <span
            className={cn(
              "inline-block h-2 w-2 rounded-full",
              pass ? "bg-green-500" : near ? "bg-amber-500" : "bg-red-500",
            )}
          />
        )}
      </div>
      <div
        className={cn(
          "mt-1 text-3xl font-semibold tabular-nums",
          value == null
            ? "text-muted-foreground"
            : pass
              ? "text-green-600 dark:text-green-400"
              : near
                ? "text-amber-600 dark:text-amber-400"
                : "text-red-600 dark:text-red-400",
        )}
      >
        {pct(value)}
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">
        {hint} · gate ≥ {Math.round(threshold * 100)}%
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}

// The freshest measurement of the shipped pipeline: single retrieval-family
// runs and the shipped arm of ablation runs compete on recency, so the
// headline can never silently lag a newer ablation shown on the same page.
function latestShippedMeasurement(allRuns: EvalRunFull[]) {
  const candidates: {
    run_at: string
    hit_rate_5: number | null
    mrr: number | null
    config: string
  }[] = []
  for (const r of allRuns) {
    if (RETRIEVAL_KINDS.has(r.eval_kind) && r.hit_rate_5 != null) {
      candidates.push({
        run_at: r.run_at,
        hit_rate_5: r.hit_rate_5,
        mrr: r.mrr,
        config: isRerank(r) ? "rerank on" : "rerank off",
      })
    } else if (r.eval_kind === "ablation") {
      const shipped = shippedAblationArm(r)
      if (shipped) {
        candidates.push({
          run_at: r.run_at,
          hit_rate_5: shipped.arm.hit_rate_5,
          mrr: shipped.arm.mrr,
          config: `ablation · ${shipped.label}`,
        })
      }
    }
  }
  candidates.sort((a, b) => b.run_at.localeCompare(a.run_at))
  return candidates[0] ?? null
}

function Delta({ base, next }: { base: number | null; next: number | null }) {
  if (base == null || next == null) return <span className="text-muted-foreground">—</span>
  const d = next - base
  const Icon = d > 0.001 ? ArrowUp : d < -0.001 ? ArrowDown : ArrowRight
  const color =
    d > 0.001 ? "text-green-600" : d < -0.001 ? "text-red-600" : "text-muted-foreground"
  return (
    <span className={cn("inline-flex items-center gap-1 font-medium tabular-nums", color)}>
      <Icon className="h-3.5 w-3.5" />
      {d >= 0 ? "+" : ""}
      {(d * 100).toFixed(1)}
    </span>
  )
}

const ABLATION_ORDER = ["vector", "fts", "graph", "rrf", "rrf+rerank"]

function AblationSection({ run }: { run: EvalRunFull }) {
  const m = run.ablation_metrics
  if (!m) return null
  const rrf = m["rrf"]
  const rrfrr = m["rrf+rerank"]
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Strategy ablation</h3>
        <span className="text-xs text-muted-foreground">
          {new Date(run.run_at).toLocaleString()}
        </span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-1.5 font-medium">Strategy</th>
            <th className="py-1.5 text-right font-medium">HR@5</th>
            <th className="py-1.5 text-right font-medium">MRR</th>
          </tr>
        </thead>
        <tbody>
          {ABLATION_ORDER.filter((s) => m[s]).map((s) => (
            <tr
              key={s}
              className={cn(
                "border-b last:border-0",
                s === "rrf+rerank" && "bg-primary/5 font-medium",
              )}
            >
              <td className="py-2">{s === "rrf+rerank" ? "rrf + rerank (shipped)" : s}</td>
              <td className="py-2 text-right tabular-nums">{pct(m[s].hit_rate_5)}</td>
              <td className="py-2 text-right tabular-nums">{pct(m[s].mrr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rrf && rrfrr && (
        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
          <span>reranker effect vs RRF:</span>
          <span className="inline-flex items-center gap-1">
            HR@5 <Delta base={rrf.hit_rate_5} next={rrfrr.hit_rate_5} />
          </span>
          <span className="inline-flex items-center gap-1">
            MRR <Delta base={rrf.mrr} next={rrfrr.mrr} />
          </span>
        </div>
      )}
    </div>
  )
}

export function ResultsDashboard({ dataset }: { dataset: string }) {
  const query = useQuery({
    queryKey: ["eval-dashboard-runs", dataset],
    queryFn: () => fetchRuns(dataset),
    enabled: Boolean(dataset),
    staleTime: 15_000,
    refetchInterval: 8_000,
  })

  if (!dataset) {
    return (
      <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
        Pick a dataset in the console above.
      </div>
    )
  }
  if (query.isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    )
  }
  const allRuns = query.data ?? []
  const runs = allRuns.filter(
    (r) => RETRIEVAL_KINDS.has(r.eval_kind) && r.status !== "failed",
  )
  const ablation = allRuns.find((r) => r.eval_kind === "ablation" && r.ablation_metrics)
  if (runs.length === 0 && !ablation) {
    return (
      <div className="grid gap-6">
        <GoldenCard dataset={dataset} />
        <div className="flex min-h-32 flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-center">
          <div className="text-sm font-medium">No eval runs yet for {dataset}</div>
          <div className="text-xs text-muted-foreground">Run an eval from the console above.</div>
        </div>
      </div>
    )
  }

  const headline = latestShippedMeasurement(allRuns)
  const baseline = runs.find((r) => !isRerank(r))
  const reranked = runs.find((r) => isRerank(r))
  // Faithfulness is only real when the run generated answers via /qa
  // (answer_model provenance). Legacy runs judged golden answers — ignore them.
  const faith = runs.find(
    (r) => r.faithfulness != null && typeof r.extra_metrics?.answer_model === "string",
  )
  const trend = [...runs]
    .reverse()
    .map((r, i) => ({ run: i + 1, "HR@5": r.hit_rate_5, MRR: r.mrr }))

  return (
    <div className="grid gap-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">{dataset}</h2>
        {headline && (
          <p className="text-xs text-muted-foreground">
            Latest measurement {new Date(headline.run_at).toLocaleString()} ({timeAgo(headline.run_at)})
            {" · "}{headline.config} · {allRuns.length} runs
            {isStale(headline.run_at) && (
              <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-700">
                stale — over 14 days old, re-run to refresh
              </span>
            )}
          </p>
        )}
      </div>

      <GoldenCard dataset={dataset} />

      {ablation && <AblationSection run={ablation} />}

      {/* Metric cards */}
      {headline && (
        <div className="grid gap-4 sm:grid-cols-3">
          <MetricCard
            label="HR@5"
            value={headline.hit_rate_5}
            threshold={THRESHOLDS.hit_rate_5}
            hint="answer in top-5 · within-document"
            sub={`${headline.config} · ${timeAgo(headline.run_at)}`}
          />
          <MetricCard
            label="MRR@5"
            value={headline.mrr}
            threshold={THRESHOLDS.mrr}
            hint="rank of first hit"
            sub={`${headline.config} · ${timeAgo(headline.run_at)}`}
          />
          <MetricCard
            label="Faithfulness"
            value={faith?.faithfulness}
            threshold={THRESHOLDS.faithfulness}
            hint={faith ? "generated answers grounded in context" : "run with a judge — answers come from live /qa"}
            sub={
              faith
                ? `judge ${faith.model_used.split("/").pop()} · answers ${String(
                    faith.extra_metrics?.answer_model,
                  )} · ${timeAgo(faith.run_at)}`
                : null
            }
          />
        </div>
      )}

      {/* Rerank A/B */}
      {baseline && reranked && (
        <div className="rounded-lg border bg-card p-4">
          <h3 className="mb-3 text-sm font-semibold">Reranker A/B</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-1.5 font-medium">Metric</th>
                <th className="py-1.5 text-right font-medium">RRF (baseline)</th>
                <th className="py-1.5 text-right font-medium">+ cross-encoder</th>
                <th className="py-1.5 text-right font-medium">Δ (pts)</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b last:border-0">
                <td className="py-2">HR@5</td>
                <td className="py-2 text-right tabular-nums">{pct(baseline.hit_rate_5)}</td>
                <td className="py-2 text-right tabular-nums">{pct(reranked.hit_rate_5)}</td>
                <td className="py-2 text-right">
                  <Delta base={baseline.hit_rate_5} next={reranked.hit_rate_5} />
                </td>
              </tr>
              <tr>
                <td className="py-2">MRR</td>
                <td className="py-2 text-right tabular-nums">{pct(baseline.mrr)}</td>
                <td className="py-2 text-right tabular-nums">{pct(reranked.mrr)}</td>
                <td className="py-2 text-right">
                  <Delta base={baseline.mrr} next={reranked.mrr} />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Trend */}
      {trend.length > 1 && (
        <div className="rounded-lg border bg-card p-4">
          <h3 className="mb-3 text-sm font-semibold">Retrieval quality over runs</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trend} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="run" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(3) : "—")} />
              <ReferenceLine y={THRESHOLDS.hit_rate_5} stroke="#94a3b8" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="HR@5" stroke="#6366f1" dot={{ r: 2 }} connectNulls />
              <Line type="monotone" dataKey="MRR" stroke="#0ea5e9" dot={{ r: 2 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
