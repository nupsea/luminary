// Recharts-based visualisations for the Monitoring page:
//   - EvalHistorySparkline: HR@5 over time per dataset
//   - RAGQualityChart:      grouped bar chart of last run per dataset
//   - QAActivityChart:      QA calls per day, trailing week
//   - TracesCard:           Phoenix link card

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { EmptyState } from "./SharedUI"
import type { EvalHistoryItem, EvalRun, PhoenixUrl, QADailyCount } from "./types"
import {
  DATASET_COLORS,
  METRIC_BARS,
  buildFunnelData,
  buildRagChartData,
  buildSparklineData,
} from "./utils"

export function EvalHistorySparkline({ history }: { history: EvalHistoryItem[] }) {
  if (history.length === 0) {
    return <EmptyState message="No eval history yet. Run make eval to populate." />
  }
  const data = buildSparklineData(history)
  const datasets = Array.from(new Set(history.map((h) => h.dataset)))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="run"
          label={{
            value: "Run",
            position: "insideBottomRight",
            offset: -4,
            fontSize: 10,
          }}
          tick={{ fontSize: 10 }}
        />
        <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
        <Tooltip
          formatter={(v, name) =>
            typeof v === "number"
              ? [v.toFixed(3), name ?? ""]
              : [v ?? "—", name ?? ""]
          }
        />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine
          y={0.6}
          stroke="#6366f1"
          strokeDasharray="4 4"
          label={{ value: "threshold 0.60", position: "insideTopRight", fontSize: 9 }}
        />
        {datasets.map((ds) => (
          <Line
            key={ds}
            type="monotone"
            dataKey={ds}
            name={ds}
            stroke={DATASET_COLORS[ds] ?? "#94a3b8"}
            dot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

export function RAGQualityChart({ evalRuns }: { evalRuns: EvalRun[] }) {
  const data = buildRagChartData(evalRuns)
  if (data.length === 0) {
    return <EmptyState message="No eval runs yet. Run evals/run_eval.py to populate." />
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="dataset" tick={{ fontSize: 11 }} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(3) : (v ?? "—"))} />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine
          y={0.65}
          stroke="#6366f1"
          strokeDasharray="4 4"
          label={{ value: "HR@5 target 0.65", position: "insideTopRight", fontSize: 10 }}
        />
        <ReferenceLine
          y={0.9}
          stroke="#22c55e"
          strokeDasharray="4 4"
          label={{ value: "Faith. target 0.9", position: "insideBottomRight", fontSize: 10 }}
        />
        {METRIC_BARS.map((m) => (
          <Bar key={m.key} dataKey={m.key} name={m.label} fill={m.color} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export function RetrievalFunnelChart({ evalRuns }: { evalRuns: EvalRun[] }) {
  const { rows, poolDepth } = buildFunnelData(evalRuns)
  if (rows.length === 0) {
    return (
      <EmptyState message="No ablation runs yet. Run an ablation eval (with L1 pool recall) to populate." />
    )
  }
  const poolLabel = `L1 pool recall${poolDepth ? `@${poolDepth}` : ""}`
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="dataset" tick={{ fontSize: 11 }} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(3) : (v ?? "—"))} />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="poolRecall" name={poolLabel} fill="#94a3b8" />
        <Bar dataKey="rrf" name="rrf HR@5 (fused)" fill="#3b82f6" />
        <Bar dataKey="rerankCe" name="rrf+rerank HR@5 (CE-only)" fill="#c084fc" />
        <Bar dataKey="rerank" name="rrf+rerank HR@5 (blended, shipped)" fill="#8b5cf6" />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function QAActivityChart({ daily }: { daily: QADailyCount[] }) {
  if (daily.every((d) => d.count === 0)) {
    return <EmptyState message="No QA activity in the last 7 days. Ask a question to populate." />
  }
  const data = daily.map((d) => ({ ...d, label: d.date.slice(5) }))
  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 10 }} />
        <YAxis allowDecimals={false} tick={{ fontSize: 10 }} width={30} />
        <Tooltip
          formatter={(v) => [v ?? 0, "QA calls"]}
          labelFormatter={(_, payload) => payload?.[0]?.payload?.date ?? ""}
        />
        <Bar
          dataKey="count"
          name="QA calls"
          fill="#6366f1"
          radius={[4, 4, 0, 0]}
          maxBarSize={28}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function TracesCard({ phoenix }: { phoenix: PhoenixUrl | null }) {
  const configured = phoenix?.configured ?? false
  const enabled = phoenix?.enabled ?? false
  const url = phoenix?.url ?? "http://localhost:6006"
  const hint = !configured
    ? "Tracing is off. Set PHOENIX_ENABLED=true in backend/.env and restart the backend — Phoenix launches in-process."
    : !enabled
      ? "Phoenix is enabled but not responding yet. It starts with the backend; give it a few seconds or check backend logs."
      : "Collecting traces for every LLM call, retrieval, and ingestion run."
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
              enabled ? "bg-green-500" : configured ? "bg-amber-500" : "bg-gray-400"
            }`}
          />
          <span className="text-sm font-medium text-foreground">
            Arize Phoenix — Distributed Tracing
          </span>
        </div>
        <span className="truncate pl-[18px] text-xs text-muted-foreground" title={hint}>
          {hint}
        </span>
      </div>
      <button
        disabled={!enabled}
        onClick={() => window.open(url, "_blank")}
        title={enabled ? "Open Phoenix UI" : hint}
        className={`shrink-0 rounded px-3 py-1 text-xs font-medium transition-colors ${
          enabled
            ? "bg-primary text-primary-foreground hover:bg-primary/90"
            : "cursor-not-allowed bg-secondary text-muted-foreground"
        }`}
      >
        Open Phoenix
      </button>
    </div>
  )
}
