// Recharts-based visualisations for the Monitoring page:
//   - QAActivityChart: QA calls per day, trailing week
//   - TracesCard:      Phoenix link card

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts"

import { EmptyState } from "./SharedUI"
import type { PhoenixUrl, QADailyCount } from "./types"
import { ChartTooltip } from "@/components/ui/chart-tooltip"

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
        <ChartTooltip

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
